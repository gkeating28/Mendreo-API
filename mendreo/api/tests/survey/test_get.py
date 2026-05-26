from rest_framework import status

from ..utils import Data
from ..utils.manager import Auth, General
from ...tests.TestCase import TestCase


class GetTest(TestCase):

    def setUp(self):
        self.consumer = Auth.create_consumer()
        self.consumer_access_token = Auth.get_consumer_access_token(self.consumer)

        self.question_one = General.create_question(Data.valid_question_data(attribute_key="sq1", survey=True))
        self.question_two = General.create_question(Data.valid_question_data(attribute_key="sq2", survey=True))

        self.non_survey_question = General.create_question(Data.valid_question_data(attribute_key="nq1", survey=False))

        self.consumer.user.email_verified = True
        self.consumer.user.save()

    def _get(self, access_token="", **kwargs):
        return super()._get("/survey", access_token=access_token)

    def test_basic_survey_response(self):
        response = self._get(self.consumer_access_token)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json
        self.assertIn("surveyed", data)
        self.assertFalse(data["surveyed"])
        self.assertTrue(data["enabled"])

        question_ids = [q["id"] for q in data["questions"]]
        self.assertIn(self.question_one.id, question_ids)
        self.assertIn(self.question_two.id, question_ids)
        self.assertNotIn(self.non_survey_question.id, question_ids)

        for q in data["questions"]:
            self.assertIsNone(q["attribute"])

    def test_attributes_attach_correctly(self):
        General.create_attribute(self.question_one, consumer=self.consumer)

        response = self._get(self.consumer_access_token)
        data = response.json

        first_q = next(q for q in data["questions"] if q["id"] == self.question_one.id)
        second_q = next(q for q in data["questions"] if q["id"] == self.question_two.id)

        self.assertIsNotNone(first_q["attribute"])
        self.assertIsNone(second_q["attribute"])

    def test_task_completion_logic(self):
        response = self._get(self.consumer_access_token)
        data = response.json
        incomplete_keys = {t["key"] for t in data["incomplete_tasks"]}
        self.assertSetEqual(incomplete_keys, {"onboarded", "viewed_post", "started_session", "sent_messages"})

        self.consumer.onboarded = True
        self.consumer.save()
        General.create_view_event(consumer=self.consumer)
        General.create_session(self.consumer)

        General.create_message(consumer=self.consumer, data=Data.valid_message_data(text="I'm feeling anxious today."))
        General.create_message(consumer=self.consumer, data=Data.valid_message_data(text="I'm feeling less focused."))
        General.create_message(consumer=self.consumer, data=Data.valid_message_data(text="I'm feeling overwhelmed today."))

        response = self._get(self.consumer_access_token)
        data = response.json
        completed_keys = {t["key"] for t in data["completed_tasks"]}
        self.assertSetEqual(completed_keys, {"onboarded", "viewed_post", "started_session", "sent_messages"})

    def test_surveyed_flag_true(self):
        self.consumer.surveyed = True
        self.consumer.save()

        response = self._get(self.consumer_access_token)
        data = response.json
        self.assertTrue(data["surveyed"])
