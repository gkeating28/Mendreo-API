from types import SimpleNamespace
from unittest.mock import patch

from django.core.cache import cache
from django.test import SimpleTestCase
from rest_framework import status

from ...agent.models import Agent
from ...ai_provider.models import AiProvider
from ...message.debug_payload import hint_ladder, prompt_layers, step_hold_decision
from ...message.models import Message, TurnPrompt
from ...message.serializers import MessageListSerializer
from ...message.turn_prompt import record_step_decision
from ...participant.models import Participant
from ...session.models import Session
from ...setting.models import Setting
from ...utils import Constants
from ...utils.Agent import GeneralResponse
from ...utils.turn_hint import (
    ACCEPT_HINT,
    DEPTH_HINT,
    FOLLOW_UP_HINT,
    goal_hint_text,
)
from ..TestCase import TestCase
from ..utils.manager import Auth


class PromptLayerTests(SimpleTestCase):
    def test_splits_tags_in_prompt_order_and_keeps_the_leftover(self):
        system = (
            "<DATA>\n"
            "<PROGRAMMING_INSTRUCTIONS>rules</PROGRAMMING_INSTRUCTIONS>\n"
            "<THERAPEUTIC_INSTRUCTIONS>tone</THERAPEUTIC_INSTRUCTIONS>\n"
            "<EXERCISE><STEPS>live step</STEPS></EXERCISE>\n"
            "<FORM_ANSWERS>yes</FORM_ANSWERS>\n"
            "<EXERCISE_SUMMARY>past run</EXERCISE_SUMMARY>\n"
            "<DATE>Thursday</DATE>\n"
            "<PENDING_QUESTION>Ask about sleep</PENDING_QUESTION>\n"
            "</DATA>"
        )
        user = (
            "<RETRIEVED>\nTitle: Worry\n</RETRIEVED>\n\n"
            "I feel stuck\n\n"
            f"<TURN_HINT>\n{FOLLOW_UP_HINT}\n</TURN_HINT>"
        )
        layers = prompt_layers(system, user)
        keys = [layer["key"] for layer in layers]
        self.assertEqual(
            keys,
            [
                "programming_instructions",
                "therapeutic_instructions",
                "exercise",
                "form_answers",
                "exercise_summary",
                "date",
                "pending_question",
                "other",
                "retrieved",
                "turn_hint",
            ],
        )
        exercise = layers[2]
        self.assertIn("<STEPS>live step</STEPS>", exercise["text"])
        self.assertEqual(exercise["source"], "exercise script")
        self.assertGreater(exercise["tokens"], 0)
        other = next(layer for layer in layers if layer["key"] == "other")
        self.assertIn("<DATA>", other["text"])
        self.assertIn("</DATA>", other["text"])
        self.assertEqual(other["source"], "system")
        self.assertEqual(layers[-2]["source"], "retrieval")
        self.assertEqual(layers[-1]["source"], "system")
        self.assertNotIn("I feel stuck", other["text"])

    def test_omits_other_when_every_character_is_inside_a_tag(self):
        layers = prompt_layers("<GOALS>one</GOALS>", "hello")
        self.assertEqual([layer["key"] for layer in layers], ["goals"])
        self.assertEqual(layers[0]["source"], "admin setting")
        self.assertEqual(layers[0]["text"], "one")


class HintLadderTests(SimpleTestCase):
    def test_thin_answer_wins_and_earlier_candidates_did_not_apply(self):
        prompted = f"ok\n\n<TURN_HINT>\n{FOLLOW_UP_HINT}\n</TURN_HINT>"
        ladder = hint_ladder(prompted)
        self.assertEqual(ladder["winner"], "thin_answer")
        by_key = {row["key"]: row for row in ladder["candidates"]}
        self.assertEqual(
            [row["key"] for row in ladder["candidates"]],
            ["not_ready", "about_the_user", "finish_summary", "goal", "depth", "thin_answer"],
        )
        self.assertTrue(by_key["thin_answer"]["won"])
        self.assertTrue(by_key["thin_answer"]["applicable"])
        self.assertIn("thin", by_key["thin_answer"]["reason"])
        self.assertFalse(by_key["goal"]["applicable"])
        self.assertIn("No goal hint", by_key["goal"]["reason"])
        self.assertFalse(by_key["depth"]["won"])

    def test_accept_hint_names_the_second_follow_up(self):
        prompted = f"ok\n\n<TURN_HINT>\n{ACCEPT_HINT}\n</TURN_HINT>"
        winner = hint_ladder(prompted)["candidates"][-1]
        self.assertTrue(winner["won"])
        self.assertIn("twice", winner["reason"])

    def test_goal_hint_stops_the_ladder(self):
        prompted = f"ok\n\n<TURN_HINT>\n{goal_hint_text('a named worry')}\n</TURN_HINT>"
        ladder = hint_ladder(prompted)
        self.assertEqual(ladder["winner"], "goal")
        by_key = {row["key"]: row for row in ladder["candidates"]}
        self.assertTrue(by_key["goal"]["applicable"])
        self.assertFalse(by_key["depth"]["applicable"])
        self.assertIn("earlier hint", by_key["depth"]["reason"])
        self.assertFalse(by_key["about_the_user"]["applicable"])

    def test_depth_hint_and_a_hint_that_is_not_on_the_ladder(self):
        depth = hint_ladder(f"<TURN_HINT>{DEPTH_HINT}</TURN_HINT>")
        self.assertEqual(depth["winner"], "depth")
        sequence = hint_ladder(
            "<TURN_HINT>\nThe next part is: Ask for a plan.\n</TURN_HINT>"
        )
        self.assertIsNone(sequence["winner"])
        self.assertTrue(all(row["won"] is False for row in sequence["candidates"]))
        self.assertTrue(all(row["applicable"] is False for row in sequence["candidates"]))

    def test_no_hint_marks_every_candidate_inapplicable(self):
        ladder = hint_ladder("just the user text")
        self.assertIsNone(ladder["winner"])
        self.assertEqual(len(ladder["candidates"]), 6)
        self.assertTrue(all(row["applicable"] is False for row in ladder["candidates"]))


class StepHoldDecisionTests(SimpleTestCase):
    def test_copies_a_hold_without_inventing_extra_fields(self):
        decision = {
            "step_no": 2,
            "model": {"step_goal_met": True, "asks_readiness": False},
            "inferred_asks_readiness": False,
            "accepted": {"step_goal_met": False, "asks_readiness": False},
            "check_done_when": {"met": False, "missing": "a named worry"},
            "goal_hint": "ask",
        }
        entry = step_hold_decision(decision)
        self.assertEqual(entry["type"], "step_hold")
        self.assertTrue(entry["fired"])
        self.assertIn("held open", entry["what"])
        self.assertIn("a named worry", entry["why"])
        self.assertEqual(entry["inputs"], decision)

    def test_missing_decision_does_not_fire(self):
        entry = step_hold_decision(None)
        self.assertFalse(entry["fired"])
        self.assertEqual(entry["inputs"], {})


class DebugEndpointTests(TestCase):
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
        self.token = Auth.get_consumer_access_token(self.consumer)
        Setting.objects.update_or_create(
            key=Constants.SETTING_KEY_STORE_TURN_PROMPTS,
            defaults={"value": "true"},
        )
        Setting.objects.update_or_create(
            key=Constants.SETTING_KEY_CHAT_DEBUG_ENABLED,
            defaults={"value": "true"},
        )
        cache.clear()

    def _reply(self, user_message):
        class _FakeAgent:
            def __init__(self, *args, **kwargs):
                pass

            def tool(self, func=None, **kwargs):
                if func is None:
                    return lambda fn: fn
                return func

            def run_sync(self, user_prompt="", message_history=None, **kwargs):
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

    def test_debug_keeps_old_fields_and_adds_layers_ladder_and_decisions(self):
        user_message = Message.objects.create(
            session=self.session,
            sender=self.user,
            text="I keep putting off the hard conversation at work.",
        )
        agent_message = self._reply(user_message)
        stored = TurnPrompt.objects.get(message=agent_message)
        kinds = [row["type"] for row in stored.decisions]
        self.assertEqual(
            kinds,
            ["thin_answer", "hint", "retrieval", "off_script", "reply_cleaner", "step_hold"],
        )
        thin = stored.decisions[0]
        self.assertEqual(thin["inputs"]["word_count"], 9)
        self.assertIn("min_words", thin["inputs"])
        self.assertIn("probe_count", thin["inputs"])
        self.assertFalse(thin["fired"])
        agent_message.refresh_from_db()
        self.assertNotIn("decisions", agent_message.usage or {})
        listed = MessageListSerializer(agent_message).data
        self.assertNotIn("decisions", listed)
        self.assertNotIn("layers", listed)
        self.assertNotIn("system_prompt", listed)

        response = self._get(
            f"/messages/{agent_message.id}/debug",
            access_token=self.token,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json)
        self.assertEqual(response.json["message_id"], agent_message.id)
        self.assertIn("system_prompt", response.json)
        self.assertIn("user_prompt", response.json)
        self.assertIn("sections", response.json)
        self.assertIn("step_decision", response.json)
        self.assertEqual(response.json["decisions"], stored.decisions)
        self.assertEqual(
            response.json["hint_ladder"]["winner"],
            hint_ladder(stored.user_prompt)["winner"],
        )
        self.assertTrue(response.json["layers"])
        self.assertIn(
            "session_context",
            [layer["key"] for layer in response.json["layers"]],
        )

    def test_step_decision_is_copied_onto_the_prompt_row_only(self):
        agent = Participant.objects.get(session=self.session, agent__isnull=False)
        message = Message.objects.create(
            session=self.session,
            sender=agent,
            text="Ready?",
            usage={
                "input_tokens": 3,
                "step_decision": {
                    "step_no": 1,
                    "model": {"step_goal_met": True, "asks_readiness": True},
                    "inferred_asks_readiness": True,
                    "accepted": {"step_goal_met": True, "asks_readiness": True},
                    "check_done_when": {"met": True, "missing": ""},
                    "goal_hint": None,
                },
            },
        )
        TurnPrompt.objects.create(
            message=message,
            system_prompt="<DATE>today</DATE>",
            user_prompt="yes",
            decisions=[{"type": "hint", "fired": False, "what": "No turn hint was added.", "why": "None.", "inputs": {}}],
        )
        record_step_decision(message)
        message.refresh_from_db()
        self.assertEqual(set(message.usage), {"input_tokens", "step_decision"})
        stored = TurnPrompt.objects.get(message=message)
        self.assertEqual([row["type"] for row in stored.decisions], ["hint", "step_hold"])
        self.assertTrue(stored.decisions[-1]["fired"])
        self.assertEqual(stored.decisions[-1]["inputs"]["step_no"], 1)
