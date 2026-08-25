from datetime import timedelta

from django.utils import timezone
from rest_framework import status

from ..utils.BaseTest import BaseTest
from ...knowledge.models import KnowledgeEntry, KnowledgeField, KnowledgeQuestion
from ...setting.models import Setting
from ...utils import Constants


class OnboardingFlowTests(BaseTest):
    def endpoint(self):
        return "onboarding"

    def setUp(self):
        super().setUp()
        Setting.get_or_create_refresh_onboarding_cadence_days()

        self.mood = KnowledgeField.objects.create(
            key="mood", label="Mood", category="Wellbeing", active=True
        )
        self.sleep = KnowledgeField.objects.create(
            key="sleep_quality", label="Sleep", category="Wellbeing", active=True
        )
        self.stress = KnowledgeField.objects.create(
            key="stress_points", label="Stress", category="Wellbeing", active=True
        )

        self.q_mood = KnowledgeQuestion.objects.create(
            prompt="How are you feeling, {{user.first_name}}?",
            target_field=self.mood,
            response_type=Constants.KNOWLEDGE_RESPONSE_TYPE_SLIDER,
            anchor_labels=["Struggling", "Thriving"],
            value_labels=["Really low"] + [""] * 9 + ["Great"],
            flows=[
                Constants.KNOWLEDGE_FLOW_INITIAL,
                Constants.KNOWLEDGE_FLOW_RETURN,
                Constants.KNOWLEDGE_FLOW_REFRESH,
            ],
            order_by_flow={"initial": 1, "return": 1, "refresh": 2},
            order=1,
            active=True,
        )
        self.q_sleep = KnowledgeQuestion.objects.create(
            prompt="Last time you said sleep was '{{knowledge.sleep_quality}}'. Any different?",
            target_field=self.sleep,
            response_type=Constants.KNOWLEDGE_RESPONSE_TYPE_SINGLE_CHOICE,
            suggested_responses=["Great", "Okay", "Poor"],
            flows=[
                Constants.KNOWLEDGE_FLOW_INITIAL,
                Constants.KNOWLEDGE_FLOW_RETURN,
                Constants.KNOWLEDGE_FLOW_REFRESH,
            ],
            order_by_flow={"initial": 2, "return": 2, "refresh": 1},
            order=2,
            active=True,
        )
        self.q_stress = KnowledgeQuestion.objects.create(
            prompt="What is stressing you?",
            target_field=self.stress,
            response_type=Constants.KNOWLEDGE_RESPONSE_TYPE_MULTIPLE_CHOICE,
            suggested_responses=["Work", "Family", "Money", "Health"],
            min_selections=1,
            max_selections=2,
            flows=[Constants.KNOWLEDGE_FLOW_INITIAL, Constants.KNOWLEDGE_FLOW_REFRESH],
            order_by_flow={"initial": 3, "refresh": 3},
            order=3,
            active=True,
        )

    def test_status_recommends_initial_before_onboarding(self):
        response = self._get_path("/onboarding/status", self.consumer_one_access_token)
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json)
        self.assertFalse(response.json["onboarded"])
        self.assertFalse(response.json["refresh_due"])
        self.assertEqual(response.json["recommended_variant"], "initial")
        self.assertEqual(response.json["cadence_days"], 30)

    def test_flow_initial_orders_and_resolves_name(self):
        self.consumer_one.user.first_name = "Ada"
        self.consumer_one.user.save(update_fields=["first_name"])

        response = self._get_path("/onboarding/flow", self.consumer_one_access_token)
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json)
        self.assertEqual(response.json["variant"], "initial")
        self.assertEqual(response.json["questions_total"], 3)
        self.assertFalse(response.json["abandonable"])
        self.assertEqual(response.json["closing_action"], "enter_mendreo")
        ids = [q["id"] for q in response.json["questions"]]
        self.assertEqual(ids, [self.q_mood.id, self.q_sleep.id, self.q_stress.id])
        self.assertIn("Ada", response.json["questions"][0]["prompt"])

    def test_complete_initial_writes_knowledge_and_onboards(self):
        payload = {
            "variant": "initial",
            "complete": True,
            "answers": [
                {"knowledge_question_id": self.q_mood.id, "value": 7},
                {"knowledge_question_id": self.q_sleep.id, "value": "Okay"},
                {
                    "knowledge_question_id": self.q_stress.id,
                    "value": ["Work", "Family"],
                },
            ],
        }
        response = self._post(
            "/onboarding/answers", payload, self.consumer_one_access_token
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json)
        self.assertTrue(response.json["complete"])
        self.assertEqual(response.json["entries_written"], 3)
        self.assertTrue(response.json["status"]["onboarded"])

        self.consumer_one.refresh_from_db()
        self.assertTrue(self.consumer_one.onboarded)
        self.assertEqual(
            self.consumer_one.last_onboarding_flow_variant,
            Constants.KNOWLEDGE_FLOW_INITIAL,
        )
        self.assertEqual(
            KnowledgeEntry.objects.filter(consumer=self.consumer_one).count(), 3
        )
        mood = KnowledgeEntry.current_for(self.consumer_one, self.mood)
        self.assertEqual(mood.value, "7")
        self.assertEqual(mood.source, Constants.KNOWLEDGE_ENTRY_SOURCE_QUESTION)

    def test_return_flow_resolves_prior_knowledge_and_is_discardable(self):
        self.consumer_one.onboarded = True
        self.consumer_one.last_onboarding_flow_completed_at = timezone.now()
        self.consumer_one.last_onboarding_flow_variant = Constants.KNOWLEDGE_FLOW_INITIAL
        self.consumer_one.save()

        KnowledgeEntry.objects.create(
            consumer=self.consumer_one,
            field=self.sleep,
            value="on and off",
            source=Constants.KNOWLEDGE_ENTRY_SOURCE_QUESTION,
        )

        flow = self._get_path(
            "/onboarding/flow",
            self.consumer_one_access_token,
            {"variant": "return"},
        )
        self.assertEqual(flow.status_code, status.HTTP_200_OK, flow.json)
        self.assertEqual(flow.json["variant"], "return")
        self.assertTrue(flow.json["abandonable"])
        self.assertEqual(flow.json["questions_total"], 2)
        sleep_q = next(q for q in flow.json["questions"] if q["id"] == self.q_sleep.id)
        self.assertIn("on and off", sleep_q["prompt"])
        self.assertEqual(sleep_q["prior_value"], "on and off")

        # Incomplete return submit rejected
        bad = self._post(
            "/onboarding/answers",
            {
                "variant": "return",
                "complete": False,
                "answers": [
                    {"knowledge_question_id": self.q_mood.id, "value": 5},
                ],
            },
            self.consumer_one_access_token,
        )
        self.assertEqual(bad.status_code, status.HTTP_400_BAD_REQUEST)

    def test_refresh_due_after_cadence(self):
        self.consumer_one.onboarded = True
        self.consumer_one.last_onboarding_flow_completed_at = timezone.now() - timedelta(
            days=31
        )
        self.consumer_one.last_onboarding_flow_variant = Constants.KNOWLEDGE_FLOW_INITIAL
        self.consumer_one.save()

        status_resp = self._get_path(
            "/onboarding/status", self.consumer_one_access_token
        )
        self.assertTrue(status_resp.json["refresh_due"])
        self.assertEqual(status_resp.json["recommended_variant"], "refresh")

        flow = self._get_path("/onboarding/flow", self.consumer_one_access_token)
        self.assertEqual(flow.json["variant"], "refresh")
        # refresh order: sleep(1), mood(2), stress(3)
        ids = [q["id"] for q in flow.json["questions"]]
        self.assertEqual(ids, [self.q_sleep.id, self.q_mood.id, self.q_stress.id])

    def test_multi_select_bounds_enforced(self):
        self.consumer_one.onboarded = False
        self.consumer_one.save(update_fields=["onboarded"])

        response = self._post(
            "/onboarding/answers",
            {
                "variant": "initial",
                "complete": True,
                "answers": [
                    {"knowledge_question_id": self.q_mood.id, "value": 4},
                    {"knowledge_question_id": self.q_sleep.id, "value": "Poor"},
                    {
                        "knowledge_question_id": self.q_stress.id,
                        "value": "Work,Family,Money",
                    },
                ],
            },
            self.consumer_one_access_token,
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_slider_out_of_range_rejected(self):
        response = self._post(
            "/onboarding/answers",
            {
                "variant": "initial",
                "complete": False,
                "answers": [
                    {"knowledge_question_id": self.q_mood.id, "value": 11},
                ],
            },
            self.consumer_one_access_token,
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_complete_shortcut_onboards_with_placeholders(self):
        response = self._post(
            "/onboarding/complete", {}, self.consumer_one_access_token
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json)
        self.assertTrue(response.json["complete"])
        self.assertEqual(response.json["variant"], "initial")
        self.assertEqual(response.json["closing_action"], "enter_mendreo")
        self.assertTrue(response.json["status"]["onboarded"])
        self.assertEqual(response.json["entries_written"], 3)

        self.consumer_one.refresh_from_db()
        self.assertTrue(self.consumer_one.onboarded)
        mood = KnowledgeEntry.current_for(self.consumer_one, self.mood)
        self.assertEqual(mood.value, "5")
        sleep = KnowledgeEntry.current_for(self.consumer_one, self.sleep)
        self.assertEqual(sleep.value, "Great")

    def test_restart_clears_onboarding_for_retest(self):
        self._post("/onboarding/complete", {}, self.consumer_one_access_token)
        self.consumer_one.refresh_from_db()
        self.assertTrue(self.consumer_one.onboarded)

        response = self._post(
            "/onboarding/restart", {}, self.consumer_one_access_token
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json)
        self.assertTrue(response.json["restarted"])
        self.assertFalse(response.json["status"]["onboarded"])
        self.assertIsNone(response.json["status"]["last_completed_at"])

        self.consumer_one.refresh_from_db()
        self.assertFalse(self.consumer_one.onboarded)
        self.assertIsNone(self.consumer_one.last_onboarding_flow_completed_at)
        self.assertEqual(
            KnowledgeEntry.objects.filter(consumer=self.consumer_one).count(), 0
        )

        flow = self._get_path("/onboarding/flow", self.consumer_one_access_token)
        self.assertEqual(flow.json["variant"], "initial")
        self.assertIsNone(flow.json["questions"][0]["prior_value"])

    def test_explicit_initial_allowed_when_onboarded(self):
        self.consumer_one.onboarded = True
        self.consumer_one.last_onboarding_flow_completed_at = timezone.now()
        self.consumer_one.last_onboarding_flow_variant = Constants.KNOWLEDGE_FLOW_INITIAL
        self.consumer_one.save()

        response = self._get_path(
            "/onboarding/flow",
            self.consumer_one_access_token,
            {"variant": "initial"},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json)
        self.assertEqual(response.json["variant"], "initial")
        self.assertEqual(response.json["questions_total"], 3)

        step = self._post(
            "/onboarding/answers",
            {
                "variant": "initial",
                "complete": False,
                "answers": [
                    {"knowledge_question_id": self.q_mood.id, "value": 6},
                ],
            },
            self.consumer_one_access_token,
        )
        self.assertEqual(step.status_code, status.HTTP_200_OK, step.json)
        self.assertFalse(step.json["complete"])

    def _get_path(self, path, access_token, query_params_dict=None):
        from ..TestCase import TestCase

        return TestCase._get(
            path,
            query_params_dict=query_params_dict or {},
            access_token=access_token,
        )
