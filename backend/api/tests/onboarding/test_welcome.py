from datetime import date

from django.test import override_settings
from django.utils import timezone
from rest_framework import status

from ..utils.BaseTest import BaseTest
from ..utils.manager import Auth
from ...asset.models import Asset
from ...image.models import Image
from ...knowledge.models import KnowledgeEntry, KnowledgeField, KnowledgeQuestion
from ...onboarding.copy import SLIDER_LABELS
from ...utils import Constants


class WelcomeFlowTests(BaseTest):
    def endpoint(self):
        return "onboarding"

    def _get_path(self, path, access_token, query_params_dict=None):
        from ..TestCase import TestCase

        return TestCase._get(
            path,
            query_params_dict=query_params_dict or {},
            access_token=access_token,
        )

    def _question(self, field, prompt, *, flow, response_type, suggested=None, order=1):
        return KnowledgeQuestion.objects.create(
            prompt=prompt,
            target_field=field,
            response_type=response_type,
            suggested_responses=suggested,
            flows=[flow],
            order_by_flow={flow: order},
            order=order,
            active=True,
        )

    def _clear_account(self):
        self.consumer_one.user.first_name = ""
        self.consumer_one.user.last_name = ""
        self.consumer_one.user.save(update_fields=["first_name", "last_name"])
        self.consumer_one.date_of_birth = None
        self.consumer_one.save(update_fields=["date_of_birth"])

    def test_status_orders_welcome_then_initial(self):
        field = KnowledgeField.objects.create(
            key="welcome_name", label="Name", category="Profile", active=True
        )
        question = self._question(
            field,
            "What should I call you?",
            flow=Constants.KNOWLEDGE_FLOW_WELCOME,
            response_type=Constants.KNOWLEDGE_RESPONSE_TYPE_TEXT,
        )
        self._clear_account()

        status_resp = self._get_path("/onboarding/status", self.consumer_one_access_token)
        self.assertEqual(status_resp.status_code, status.HTTP_200_OK, status_resp.json)
        self.assertEqual(status_resp.json["recommended_variant"], "welcome")
        self.assertEqual(status_resp.json["next_step"], "welcome")
        self.assertFalse(status_resp.json["onboarded"])

        blocked = self._get_path(
            "/onboarding/flow",
            self.consumer_one_access_token,
            {"variant": "initial"},
        )
        self.assertEqual(blocked.status_code, status.HTTP_400_BAD_REQUEST)

        submitted = self._post(
            "/onboarding/answers",
            {
                "variant": "welcome",
                "complete": True,
                "answers": [{"knowledge_question_id": question.id, "value": "Ada"}],
            },
            self.consumer_one_access_token,
        )
        self.assertEqual(submitted.status_code, status.HTTP_200_OK, submitted.json)
        self.assertFalse(submitted.json["status"]["onboarded"])
        self.assertEqual(submitted.json["status"]["next_step"], "initial")

        self.consumer_one.refresh_from_db()
        self.assertFalse(self.consumer_one.onboarded)
        self.assertIsNotNone(self.consumer_one.welcome_completed_at)
        entry = KnowledgeEntry.current_for(self.consumer_one, field)
        self.assertEqual(entry.source, Constants.KNOWLEDGE_ENTRY_SOURCE_WELCOME)

    def test_welcome_is_skipped_once_onboarded_and_returns_after_restart(self):
        field = KnowledgeField.objects.create(
            key="welcome_name", label="Name", category="Profile", active=True
        )
        self._question(
            field,
            "What should I call you?",
            flow=Constants.KNOWLEDGE_FLOW_WELCOME,
            response_type=Constants.KNOWLEDGE_RESPONSE_TYPE_TEXT,
        )
        self._clear_account()
        self.consumer_one.onboarded = True
        self.consumer_one.welcome_completed_at = None
        self.consumer_one.last_onboarding_flow_completed_at = timezone.now()
        self.consumer_one.last_onboarding_flow_variant = Constants.KNOWLEDGE_FLOW_INITIAL
        self.consumer_one.save(
            update_fields=[
                "onboarded",
                "welcome_completed_at",
                "last_onboarding_flow_completed_at",
                "last_onboarding_flow_variant",
            ]
        )

        onboarded = self._get_path("/onboarding/status", self.consumer_one_access_token)
        self.assertEqual(onboarded.status_code, status.HTTP_200_OK, onboarded.json)
        self.assertIn(onboarded.json["next_step"], ("return", "refresh"))
        self.assertEqual(onboarded.json["recommended_variant"], onboarded.json["next_step"])
        self.assertEqual(onboarded.json["next_step"], "return")

        self.consumer_one.onboarded = False
        self.consumer_one.save(update_fields=["onboarded"])
        not_onboarded = self._get_path(
            "/onboarding/status", self.consumer_one_access_token
        )
        self.assertEqual(not_onboarded.json["next_step"], "welcome")
        self.assertEqual(not_onboarded.json["recommended_variant"], "welcome")

        self.consumer_one.onboarded = True
        self.consumer_one.save(update_fields=["onboarded"])
        restarted = self._post(
            "/onboarding/restart", {}, self.consumer_one_access_token
        )
        self.assertEqual(restarted.status_code, status.HTTP_200_OK, restarted.json)
        self.assertFalse(restarted.json["status"]["onboarded"])
        self.assertEqual(restarted.json["status"]["next_step"], "welcome")
        self.assertEqual(restarted.json["status"]["recommended_variant"], "welcome")

    def test_no_welcome_questions_skips_straight_to_initial(self):
        response = self._get_path("/onboarding/status", self.consumer_one_access_token)
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json)
        self.assertEqual(response.json["recommended_variant"], "initial")
        self.assertEqual(response.json["next_step"], "initial")
        self.consumer_one.refresh_from_db()
        self.assertIsNone(self.consumer_one.welcome_completed_at)

    def test_skip_if_known_for_a_registered_user(self):
        name = KnowledgeField.objects.create(
            key="given_name",
            label="First name",
            category="Profile",
            sync_to=Constants.KNOWLEDGE_SYNC_FIRST_NAME,
            active=True,
        )
        pronouns = KnowledgeField.objects.create(
            key="pronouns", label="Pronouns", category="Profile", active=True
        )
        self._question(
            name,
            "Your name?",
            flow=Constants.KNOWLEDGE_FLOW_WELCOME,
            response_type=Constants.KNOWLEDGE_RESPONSE_TYPE_TEXT,
        )
        self._question(
            pronouns,
            "Your pronouns?",
            flow=Constants.KNOWLEDGE_FLOW_WELCOME,
            response_type=Constants.KNOWLEDGE_RESPONSE_TYPE_TEXT,
            order=2,
        )
        self.consumer_one.user.first_name = "Ada"
        self.consumer_one.user.save(update_fields=["first_name"])

        flow = self._get_path(
            "/onboarding/flow",
            self.consumer_one_access_token,
            {"variant": "welcome"},
        )
        self.assertEqual(flow.status_code, status.HTTP_200_OK, flow.json)
        prompts = [question["prompt"] for question in flow.json["questions"]]
        self.assertEqual(prompts, ["Your pronouns?"])
        self.assertEqual(flow.json["questions_total"], 1)

    def test_skip_if_known_does_not_hide_empty_fields(self):
        name = KnowledgeField.objects.create(
            key="given_name",
            label="First name",
            category="Profile",
            sync_to=Constants.KNOWLEDGE_SYNC_FIRST_NAME,
            active=True,
        )
        pronouns = KnowledgeField.objects.create(
            key="pronouns", label="Pronouns", category="Profile", active=True
        )
        self._question(
            name,
            "Your name?",
            flow=Constants.KNOWLEDGE_FLOW_WELCOME,
            response_type=Constants.KNOWLEDGE_RESPONSE_TYPE_TEXT,
        )
        self._question(
            pronouns,
            "Your pronouns?",
            flow=Constants.KNOWLEDGE_FLOW_WELCOME,
            response_type=Constants.KNOWLEDGE_RESPONSE_TYPE_TEXT,
            order=2,
        )
        self._clear_account()

        flow = self._get_path(
            "/onboarding/flow",
            self.consumer_one_access_token,
            {"variant": "welcome"},
        )
        self.assertEqual(flow.status_code, status.HTTP_200_OK, flow.json)
        prompts = [question["prompt"] for question in flow.json["questions"]]
        self.assertEqual(prompts, ["Your name?", "Your pronouns?"])
        self.assertEqual(flow.json["questions_total"], 2)

        KnowledgeEntry.objects.create(
            consumer=self.consumer_one,
            field=pronouns,
            value="they/them",
            source=Constants.KNOWLEDGE_ENTRY_SOURCE_ADMIN,
        )
        again = self._get_path(
            "/onboarding/flow",
            self.consumer_one_access_token,
            {"variant": "welcome"},
        )
        prompts = [question["prompt"] for question in again.json["questions"]]
        self.assertEqual(prompts, ["Your name?"])

    def test_sync_writes_name_and_date_of_birth(self):
        name = KnowledgeField.objects.create(
            key="given_name",
            label="First name",
            category="Profile",
            sync_to=Constants.KNOWLEDGE_SYNC_FIRST_NAME,
            active=True,
        )
        born = KnowledgeField.objects.create(
            key="born_on",
            label="Date of birth",
            category="Profile",
            sync_to=Constants.KNOWLEDGE_SYNC_DATE_OF_BIRTH,
            active=True,
        )
        name_q = self._question(
            name,
            "Your name?",
            flow=Constants.KNOWLEDGE_FLOW_WELCOME,
            response_type=Constants.KNOWLEDGE_RESPONSE_TYPE_TEXT,
        )
        born_q = self._question(
            born,
            "When were you born?",
            flow=Constants.KNOWLEDGE_FLOW_WELCOME,
            response_type=Constants.KNOWLEDGE_RESPONSE_TYPE_DATE,
            order=2,
        )
        self._clear_account()

        response = self._post(
            "/onboarding/answers",
            {
                "variant": "welcome",
                "complete": True,
                "answers": [
                    {"knowledge_question_id": name_q.id, "value": "Ada"},
                    {"knowledge_question_id": born_q.id, "value": "1990-01-15"},
                ],
            },
            self.consumer_one_access_token,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json)
        self.consumer_one.refresh_from_db()
        self.consumer_one.user.refresh_from_db()
        self.assertEqual(self.consumer_one.user.first_name, "Ada")
        self.assertEqual(self.consumer_one.date_of_birth, date(1990, 1, 15))
        self.assertFalse(self.consumer_one.onboarded)
        self.assertEqual(
            KnowledgeEntry.current_for(self.consumer_one, born).value, "1990-01-15"
        )

    def test_under_18_saves_nothing(self):
        name = KnowledgeField.objects.create(
            key="given_name",
            label="First name",
            category="Profile",
            sync_to=Constants.KNOWLEDGE_SYNC_FIRST_NAME,
            active=True,
        )
        born = KnowledgeField.objects.create(
            key="born_on",
            label="Date of birth",
            category="Profile",
            sync_to=Constants.KNOWLEDGE_SYNC_DATE_OF_BIRTH,
            active=True,
        )
        name_q = self._question(
            name,
            "Your name?",
            flow=Constants.KNOWLEDGE_FLOW_WELCOME,
            response_type=Constants.KNOWLEDGE_RESPONSE_TYPE_TEXT,
        )
        born_q = self._question(
            born,
            "When were you born?",
            flow=Constants.KNOWLEDGE_FLOW_WELCOME,
            response_type=Constants.KNOWLEDGE_RESPONSE_TYPE_DATE,
            order=2,
        )
        self._clear_account()

        response = self._post(
            "/onboarding/answers",
            {
                "variant": "welcome",
                "complete": True,
                "answers": [
                    {"knowledge_question_id": name_q.id, "value": "Ada"},
                    {"knowledge_question_id": born_q.id, "value": "2015-06-01"},
                ],
            },
            self.consumer_one_access_token,
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        detail = response.json["detail"]
        if isinstance(detail, list):
            detail = detail[0]
        self.assertEqual(detail, "You need to be 18 or over to use Mendreo.")

        self.consumer_one.refresh_from_db()
        self.consumer_one.user.refresh_from_db()
        self.assertEqual(self.consumer_one.user.first_name, "")
        self.assertIsNone(self.consumer_one.date_of_birth)
        self.assertIsNone(self.consumer_one.welcome_completed_at)
        self.assertFalse(
            KnowledgeEntry.objects.filter(consumer=self.consumer_one).exists()
        )

    def test_restart_wipes_welcome_and_onboarding_and_resets(self):
        field = KnowledgeField.objects.create(
            key="welcome_name", label="Name", category="Profile", active=True
        )
        question = self._question(
            field,
            "What should I call you?",
            flow=Constants.KNOWLEDGE_FLOW_WELCOME,
            response_type=Constants.KNOWLEDGE_RESPONSE_TYPE_TEXT,
        )
        self._clear_account()
        self._post(
            "/onboarding/answers",
            {
                "variant": "welcome",
                "complete": True,
                "answers": [{"knowledge_question_id": question.id, "value": "Ada"}],
            },
            self.consumer_one_access_token,
        )
        other = KnowledgeField.objects.create(
            key="from_chat", label="From chat", category="Profile", active=True
        )
        kept = KnowledgeEntry.objects.create(
            consumer=self.consumer_one,
            field=other,
            value="from chat",
            source=Constants.KNOWLEDGE_ENTRY_SOURCE_AI,
        )

        response = self._post("/onboarding/restart", {}, self.consumer_one_access_token)
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json)
        self.assertEqual(response.json["status"]["next_step"], "welcome")

        self.consumer_one.refresh_from_db()
        self.assertIsNone(self.consumer_one.welcome_completed_at)
        self.assertFalse(self.consumer_one.onboarded)
        self.assertFalse(
            KnowledgeEntry.objects.filter(
                consumer=self.consumer_one,
                source=Constants.KNOWLEDGE_ENTRY_SOURCE_WELCOME,
            ).exists()
        )
        self.assertTrue(KnowledgeEntry.objects.filter(id=kept.id).exists())

    def _stamp_welcome_done(self):
        self.consumer_one.welcome_completed_at = self.consumer_one.created_at
        self.consumer_one.onboarded = True
        self.consumer_one.save(update_fields=["welcome_completed_at", "onboarded"])

    def test_restart_allow_list(self):
        allowed = ("local", "worker")
        hidden = ("vercel", "production", "anything-else")

        for target in allowed:
            with self.subTest(target=target):
                self._stamp_welcome_done()
                with override_settings(DEPLOYMENT_TARGET=target):
                    response = self._post(
                        "/onboarding/restart", {}, self.consumer_one_access_token
                    )
                self.assertEqual(response.status_code, status.HTTP_200_OK, target)
                self.consumer_one.refresh_from_db()
                self.assertIsNone(self.consumer_one.welcome_completed_at)
                self.assertFalse(self.consumer_one.onboarded)

        for target in hidden:
            with self.subTest(target=target):
                self._stamp_welcome_done()
                with override_settings(DEPLOYMENT_TARGET=target):
                    response = self._post(
                        "/onboarding/restart", {}, self.consumer_one_access_token
                    )
                self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND, target)
                self.consumer_one.refresh_from_db()
                self.assertIsNotNone(self.consumer_one.welcome_completed_at)
                self.assertTrue(self.consumer_one.onboarded)

    def test_old_client_without_welcome_questions_is_unchanged(self):
        mood = KnowledgeField.objects.create(
            key="mood", label="Mood", category="Wellbeing", active=True
        )
        question = self._question(
            mood,
            "How are you?",
            flow=Constants.KNOWLEDGE_FLOW_INITIAL,
            response_type=Constants.KNOWLEDGE_RESPONSE_TYPE_SLIDER,
        )

        status_resp = self._get_path("/onboarding/status", self.consumer_one_access_token)
        self.assertEqual(status_resp.json["recommended_variant"], "initial")
        self.assertEqual(status_resp.json["next_step"], "initial")
        self.assertFalse(status_resp.json["onboarded"])

        flow = self._get_path("/onboarding/flow", self.consumer_one_access_token)
        self.assertEqual(flow.status_code, status.HTTP_200_OK, flow.json)
        self.assertEqual(flow.json["variant"], "initial")
        self.assertEqual(flow.json["questions_total"], 1)
        self.assertEqual(flow.json["closing_action"], "enter_mendreo")
        self.assertFalse(flow.json["abandonable"])

        submitted = self._post(
            "/onboarding/answers",
            {
                "variant": "initial",
                "complete": True,
                "answers": [{"knowledge_question_id": question.id, "value": 6}],
            },
            self.consumer_one_access_token,
        )
        self.assertEqual(submitted.status_code, status.HTTP_200_OK, submitted.json)
        self.assertTrue(submitted.json["status"]["onboarded"])
        self.consumer_one.refresh_from_db()
        self.assertTrue(self.consumer_one.onboarded)
        self.assertIsNone(self.consumer_one.welcome_completed_at)
        entry = KnowledgeEntry.current_for(self.consumer_one, mood)
        self.assertEqual(entry.source, Constants.KNOWLEDGE_ENTRY_SOURCE_ONBOARDING)

    def test_answers_stay_on_the_requesting_consumer(self):
        field = KnowledgeField.objects.create(
            key="welcome_name", label="Name", category="Profile", active=True
        )
        question = self._question(
            field,
            "What should I call you?",
            flow=Constants.KNOWLEDGE_FLOW_WELCOME,
            response_type=Constants.KNOWLEDGE_RESPONSE_TYPE_TEXT,
        )
        self._clear_account()
        other = Auth.create_consumer()
        other.user.first_name = ""
        other.user.save(update_fields=["first_name"])
        other.date_of_birth = None
        other.save(update_fields=["date_of_birth"])

        self._post(
            "/onboarding/answers",
            {
                "variant": "welcome",
                "complete": True,
                "answers": [{"knowledge_question_id": question.id, "value": "Ada"}],
            },
            self.consumer_one_access_token,
        )
        self.assertFalse(KnowledgeEntry.objects.filter(consumer=other).exists())
        other_status = self._get_path(
            "/onboarding/status", Auth.get_access_token(other.user)
        )
        self.assertEqual(other_status.json["next_step"], "welcome")

    def test_copy_defaults_tokens_and_blank_fallback(self):
        field = KnowledgeField.objects.create(
            key="welcome_name", label="Name", category="Profile", active=True
        )
        self._question(
            field,
            "Hello",
            flow=Constants.KNOWLEDGE_FLOW_WELCOME,
            response_type=Constants.KNOWLEDGE_RESPONSE_TYPE_TEXT,
        )
        self.consumer_one.user.first_name = "Ada"
        self.consumer_one.user.save(update_fields=["first_name"])

        flow = self._get_path(
            "/onboarding/flow",
            self.consumer_one_access_token,
            {"variant": "welcome"},
        )
        self.assertEqual(
            flow.json["copy"]["greeting"],
            "Hello Ada — I'm Toni. A couple of things before we start.",
        )
        self.assertEqual(flow.json["copy"]["slider_labels"], SLIDER_LABELS)
        self.assertEqual(flow.json["copy"]["notice_start"], "Welcome")

        token = Auth.get_platform_admin_access_token()
        saved = self._post(
            "/settings",
            {
                "survey_enabled": True,
                "onboarding_copy_welcome": {
                    "greeting": "{Hello|Hello Name} — welcome in.",
                },
            },
            token,
        )
        self.assertEqual(saved.status_code, status.HTTP_200_OK, saved.data)
        self.assertEqual(
            saved.data["onboarding_copy_welcome"]["greeting"],
            "{Hello|Hello Name} — welcome in.",
        )

        overridden = self._get_path(
            "/onboarding/flow",
            self.consumer_one_access_token,
            {"variant": "welcome"},
        )
        self.assertEqual(
            overridden.json["copy"]["greeting"],
            "Hello Ada — welcome in.",
        )
        self.assertEqual(overridden.json["copy"]["notice_start"], "Welcome")

        blank = self._post(
            "/settings",
            {
                "survey_enabled": True,
                "onboarding_copy_welcome": {"greeting": ""},
            },
            token,
        )
        self.assertEqual(blank.status_code, status.HTTP_200_OK, blank.data)
        restored = self._get_path(
            "/onboarding/flow",
            self.consumer_one_access_token,
            {"variant": "welcome"},
        )
        self.assertEqual(
            restored.json["copy"]["greeting"],
            "Hello Ada — I'm Toni. A couple of things before we start.",
        )

    def test_chip_replies_validation_and_orphan_drop(self):
        field = KnowledgeField.objects.create(
            key="ready", label="Ready", category="Profile", active=True
        )
        image = Image.objects.create(
            created_by=self.admin_one.user,
            original="original",
            name="chip",
            width=1,
            height=1,
        )
        image_asset = Asset.objects.create(image=image, context="chip")
        file_asset = Asset.objects.create(context="not an image")

        rejected_key = self._post(
            "/knowledge-questions",
            {
                "prompt": "Ready?",
                "target_field": field.id,
                "response_type": Constants.KNOWLEDGE_RESPONSE_TYPE_SINGLE_CHOICE,
                "suggested_responses": ["Yes", "No"],
                "chip_replies": {"Maybe": {"reply": "Okay", "media": None}},
                "flows": [Constants.KNOWLEDGE_FLOW_WELCOME],
            },
            self.admin_one_access_token,
        )
        self.assertEqual(rejected_key.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("suggested_responses", str(rejected_key.json))

        rejected_length = self._post(
            "/knowledge-questions",
            {
                "prompt": "Ready?",
                "target_field": field.id,
                "response_type": Constants.KNOWLEDGE_RESPONSE_TYPE_SINGLE_CHOICE,
                "suggested_responses": ["Yes", "No"],
                "chip_replies": {"Yes": {"reply": "y" * 501, "media": None}},
                "flows": [Constants.KNOWLEDGE_FLOW_WELCOME],
            },
            self.admin_one_access_token,
        )
        self.assertEqual(rejected_length.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("500", str(rejected_length.json))

        rejected_media = self._post(
            "/knowledge-questions",
            {
                "prompt": "Ready?",
                "target_field": field.id,
                "response_type": Constants.KNOWLEDGE_RESPONSE_TYPE_SINGLE_CHOICE,
                "suggested_responses": ["Yes", "No"],
                "chip_replies": {"Yes": {"reply": "Glad you're here.", "media": file_asset.id}},
                "flows": [Constants.KNOWLEDGE_FLOW_WELCOME],
            },
            self.admin_one_access_token,
        )
        self.assertEqual(rejected_media.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("image asset", str(rejected_media.json))

        created = self._post(
            "/knowledge-questions",
            {
                "prompt": "Ready?",
                "target_field": field.id,
                "response_type": Constants.KNOWLEDGE_RESPONSE_TYPE_SINGLE_CHOICE,
                "suggested_responses": ["Yes", "No", "Later"],
                "chip_replies": {
                    "Yes": {"reply": "Glad you're here.", "media": image_asset.id},
                    "No": {"reply": "We can pause.", "media": None},
                    "Later": {"reply": "Whenever you like.", "media": None},
                },
                "flows": [Constants.KNOWLEDGE_FLOW_WELCOME],
            },
            self.admin_one_access_token,
        )
        self.assertEqual(created.status_code, status.HTTP_201_CREATED, created.json)
        self.assertEqual(created.json["chip_replies"]["Yes"]["media"], image_asset.id)
        self.assertEqual(created.json["target_field"]["sync_to"], "none")

        edited = self._patch(
            f"/knowledge-questions/{created.json['id']}",
            {"suggested_responses": ["Yes", "No"]},
            self.admin_one_access_token,
        )
        self.assertEqual(edited.status_code, status.HTTP_200_OK, edited.json)
        self.assertEqual(set(edited.json["chip_replies"]), {"Yes", "No"})
        self.assertNotIn("Later", edited.json["chip_replies"])
