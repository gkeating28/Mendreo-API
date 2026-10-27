from types import SimpleNamespace
from unittest.mock import patch

from django.core.cache import cache
from rest_framework import status

from ...agent.models import Agent
from ...ai_provider.models import AiProvider
from ...message.models import Message, TurnPrompt
from ...message.serializers import MessageListSerializer
from ...message.turn_prompt import history_rows
from ...participant.models import Participant
from ...session.models import Session
from ...setting.models import Setting
from ...utils import Constants
from ...utils.Agent import GeneralResponse
from ..TestCase import TestCase
from ..utils.manager import Auth


class HistoryRowTests(TestCase):
    def test_reads_user_and_assistant_parts(self):
        class ModelRequest:
            parts = [SimpleNamespace(content="Earlier in this session:\nhello")]

        class ModelResponse:
            parts = [SimpleNamespace(content="Hi")]

        rows = history_rows([ModelRequest(), ModelResponse()])
        self.assertEqual(
            rows,
            [
                {"role": "user", "text": "Earlier in this session:\nhello"},
                {"role": "assistant", "text": "Hi"},
            ],
        )


class TurnPromptTests(TestCase):
    def setUp(self):
        super().setUp()
        AiProvider.objects.all().delete()
        provider = AiProvider(
            name="Google",
            provider=Constants.AI_PROVIDER_GOOGLE,
            default_model="gemini-2.5-pro",
            is_default=True,
            enabled=True,
        )
        provider.set_api_key("google-secret")
        provider.save()
        self.consumer = Auth.create_consumer()
        self.session = Session.create_general(self.consumer)
        self.user = Participant.objects.get(session=self.session, consumer__isnull=False)
        self.text = "I keep putting off the hard conversation at work."

    def _enable(self, value):
        Setting.objects.update_or_create(
            key=Constants.SETTING_KEY_STORE_TURN_PROMPTS,
            defaults={"value": "true" if value else "false"},
        )
        cache.clear()

    def _user_message(self):
        return Message.objects.create(
            session=self.session,
            sender=self.user,
            text=self.text,
        )

    def _reply(self, user_message, *, fail=False):
        class _FakeAgent:
            def __init__(self, *args, **kwargs):
                pass

            def tool(self, func=None, **kwargs):
                if func is None:
                    return lambda fn: fn
                return func

            def run_sync(self, user_prompt="", message_history=None, **kwargs):
                if fail:
                    raise RuntimeError("model down")
                output = GeneralResponse(
                    text="What is the conversation about?",
                    suggested_responses=[],
                    reasoning="ok",
                )
                return SimpleNamespace(
                    output=output,
                    usage=lambda: SimpleNamespace(input_tokens=1, output_tokens=1),
                )

        with (
            patch("api.utils.Agent.build_pydantic_model", return_value=(object(), None)),
            patch("api.utils.Agent.Agent", _FakeAgent),
        ):
            return Agent.get_response(self.session, user_message)

    def test_admin_reads_a_stored_prompt_and_404s_without_one(self):
        agent = Participant.objects.get(session=self.session, agent__isnull=False)
        assistant = Message.objects.create(
            session=self.session,
            sender=agent,
            text="What is the conversation about?",
        )
        TurnPrompt.objects.create(
            message=assistant,
            model_name="gemini-2.5-pro",
            system_prompt="system body",
            user_prompt="user body",
            history=[],
        )
        found = self._get(
            f"/messages/{assistant.id}/prompt",
            access_token=Auth.get_platform_admin_access_token(),
        )
        self.assertEqual(found.status_code, status.HTTP_200_OK)
        self.assertEqual(found.json["system_prompt"], "system body")
        self.assertEqual(found.json["user_prompt"], "user body")

        bare = Message.objects.create(
            session=self.session,
            sender=agent,
            text="no prompt stored",
        )
        missing = self._get(
            f"/messages/{bare.id}/prompt",
            access_token=Auth.get_platform_admin_access_token(),
        )
        self.assertEqual(missing.status_code, status.HTTP_404_NOT_FOUND)

    def test_stores_the_prompt_on_the_assistant_message(self):
        self._enable(True)
        user_message = self._user_message()
        agent_message = self._reply(user_message)

        stored = TurnPrompt.objects.get(message=agent_message)
        provider = AiProvider.get_default()
        self.assertEqual(
            stored.model_name,
            provider.resolve_model_name(self.consumer.agent.model),
        )
        self.assertIn(self.text, stored.user_prompt)
        self.assertIn("<SESSION_CONTEXT>", stored.system_prompt)
        self.assertEqual(stored.history, [])

        listed = MessageListSerializer(agent_message).data
        self.assertNotIn("system_prompt", listed)
        self.assertNotIn("user_prompt", listed)
        self.assertNotIn("turn_prompt", listed)

        admin = self._get(
            f"/messages/{agent_message.id}/prompt",
            access_token=Auth.get_platform_admin_access_token(),
        )
        self.assertEqual(admin.status_code, status.HTTP_200_OK)
        self.assertEqual(admin.json["message_id"], agent_message.id)
        self.assertIn(self.text, admin.json["user_prompt"])

        denied = self._get(
            f"/messages/{agent_message.id}/prompt",
            access_token=Auth.get_consumer_access_token(self.consumer),
        )
        self.permission_denied_test(denied)

        missing = self._get(
            f"/messages/{user_message.id}/prompt",
            access_token=Auth.get_platform_admin_access_token(),
        )
        self.assertEqual(missing.status_code, status.HTTP_404_NOT_FOUND)

    def test_failed_turn_still_stores_the_prompt(self):
        self._enable(True)
        agent_message = self._reply(self._user_message(), fail=True)
        stored = TurnPrompt.objects.get(message=agent_message)
        self.assertIn(self.text, stored.user_prompt)
        self.assertIn("issue understanding", agent_message.text)

    def test_setting_can_be_turned_on(self):
        response = self._post(
            "/settings",
            {"survey_enabled": True, "store_turn_prompts": True},
            access_token=Auth.get_platform_admin_access_token(),
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.json["store_turn_prompts"])
        self.assertTrue(Setting.get_store_turn_prompts())

    def test_setting_off_stores_nothing(self):
        self._enable(False)
        agent_message = self._reply(self._user_message())
        self.assertFalse(TurnPrompt.objects.filter(message=agent_message).exists())
        missing = self._get(
            f"/messages/{agent_message.id}/prompt",
            access_token=Auth.get_platform_admin_access_token(),
        )
        self.assertEqual(missing.status_code, status.HTTP_404_NOT_FOUND)
