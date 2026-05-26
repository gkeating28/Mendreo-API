import json

from ...tests.TestCase import TestCase

from rest_framework import status

from ..utils import Data
from ..utils.manager import Auth, General


class GetTest(TestCase):

    def setUp(self):
        self.admin = Auth.create_admin()

        self.admin_access_token = Auth.get_access_token(self.admin.user)

        self.question_one = General.create_question(Data.valid_question_data(attribute_key="q1"))
        self.question_two = General.create_question(Data.valid_question_data(attribute_key="q2"))
        self.question_three = General.create_question(Data.valid_question_data(attribute_key="q3"))

        self.survey_question_one = General.create_question(Data.valid_question_data(attribute_key="sq1", survey=True))

        self.consumer = Auth.create_consumer()
        self.consumer_access_token = Auth.get_consumer_access_token(self.consumer)

        self.consumer.user.email_verified = True
        self.consumer.user.save()

        self.assertFalse(self.consumer.onboarded)

    def _get(self, access_token="", **kwargs):
        response = super()._get(f"/onboarding", access_token=access_token)

        return response

    def test_basic(self):

        onboarding_response = self._get(self.consumer_access_token)

        self.assertEqual(onboarding_response.status_code, status.HTTP_200_OK)

        onboarding_response_json = onboarding_response.json
        self.assertFalse(onboarding_response_json["onboarded"])
        self.assertEqual(len(onboarding_response_json["packages"]), 1)

        self.assertEqual(len(onboarding_response_json["questions"]), 3)

        self.assertEqual(onboarding_response_json["questions"][0]["id"], self.question_one.id)
        self.assertEqual(onboarding_response_json["questions"][1]["id"], self.question_two.id)
        self.assertEqual(onboarding_response_json["questions"][2]["id"], self.question_three.id)

        self.assertIsNone(onboarding_response_json["questions"][0]["attribute"])
        self.assertIsNone(onboarding_response_json["questions"][1]["attribute"])
        self.assertIsNone(onboarding_response_json["questions"][2]["attribute"])

        # Answer 1st Question
        General.create_attribute(self.question_one, consumer=self.consumer)

        onboarding_response = self._get(self.consumer_access_token)

        self.assertEqual(onboarding_response.status_code, status.HTTP_200_OK)

        onboarding_response_json = onboarding_response.json
        self.assertFalse(onboarding_response_json["onboarded"])

        self.assertIsNotNone(onboarding_response_json["questions"][0]["attribute"])
        self.assertIsNone(onboarding_response_json["questions"][1]["attribute"])
        self.assertIsNone(onboarding_response_json["questions"][2]["attribute"])

        # Answer 2nd Question
        General.create_attribute(self.question_two, consumer=self.consumer)

        onboarding_response = self._get(self.consumer_access_token)

        self.assertEqual(onboarding_response.status_code, status.HTTP_200_OK)

        onboarding_response_json = onboarding_response.json
        self.assertFalse(onboarding_response_json["onboarded"])

        self.assertIsNotNone(onboarding_response_json["questions"][0]["attribute"])
        self.assertIsNotNone(onboarding_response_json["questions"][1]["attribute"])
        self.assertIsNone(onboarding_response_json["questions"][2]["attribute"])

        # Answer 3rd Question
        General.create_attribute(self.question_three, consumer=self.consumer)

        onboarding_response = self._get(self.consumer_access_token)

        self.assertEqual(onboarding_response.status_code, status.HTTP_200_OK)

        onboarding_response_json = onboarding_response.json
        self.assertFalse(onboarding_response_json["onboarded"])

        self.assertIsNotNone(onboarding_response_json["questions"][0]["attribute"])
        self.assertIsNotNone(onboarding_response_json["questions"][1]["attribute"])
        self.assertIsNotNone(onboarding_response_json["questions"][2]["attribute"])

        # Pay for subscription
        General.subscribe_to_paid_package(self.consumer)

        onboarding_response = self._get(self.consumer_access_token)

        self.assertEqual(onboarding_response.status_code, status.HTTP_200_OK)

        onboarding_response_json = onboarding_response.json
        self.assertTrue(onboarding_response_json["onboarded"])

    def test_complete_attributes_first(self):

        General.create_attribute(self.question_one, consumer=self.consumer)
        General.create_attribute(self.question_two, consumer=self.consumer)
        General.create_attribute(self.question_three, consumer=self.consumer)

        self.consumer.refresh_from_db()
        self.assertFalse(self.consumer.onboarded)

        General.subscribe_to_paid_package(self.consumer)

        self.consumer.refresh_from_db()
        self.assertTrue(self.consumer.onboarded)

    def test_pay_subscription_first(self):

        General.subscribe_to_paid_package(self.consumer)

        self.consumer.refresh_from_db()
        self.assertFalse(self.consumer.onboarded)

        General.create_attribute(self.question_one, consumer=self.consumer)
        General.create_attribute(self.question_two, consumer=self.consumer)
        General.create_attribute(self.question_three, consumer=self.consumer)

        self.consumer.refresh_from_db()
        self.assertTrue(self.consumer.onboarded)

    def test_cancel_subscription(self):

        General.create_attribute(self.question_one, consumer=self.consumer)
        General.create_attribute(self.question_two, consumer=self.consumer)
        General.create_attribute(self.question_three, consumer=self.consumer)

        General.subscribe_to_paid_package(self.consumer, method="stripe")

        self.consumer.refresh_from_db()
        self.assertTrue(self.consumer.onboarded)

        cancel_response = self._delete(
            endpoint=f"/subscriptions/{self.consumer.user_id}",
            access_token=self.consumer_access_token
        )

        self.assertEqual(cancel_response.status_code, status.HTTP_204_NO_CONTENT)

        self.consumer.refresh_from_db()

        self.assertEqual(self.consumer.onboarded, False)

    def test_social_auth_update_dob_separately(self):
        self.consumer = Auth.social_login(provider="apple")
        self.consumer_access_token = Auth.get_consumer_access_token(self.consumer)

        edit_user_response = self._patch(
            endpoint=f"/consumers/{self.consumer.user_id}",
            data={
                "date_of_birth": "2000-01-01",
                "user": {
                    "first_name": "John",
                    "last_name": "Doe"
                }
            },
            access_token=self.consumer_access_token
        )

        self.assertEqual(edit_user_response.status_code, status.HTTP_200_OK)

        onboarding_response = self._get(self.consumer_access_token)

        self.assertEqual(onboarding_response.status_code, status.HTTP_200_OK)

        onboarding_response_json = onboarding_response.json
        self.assertFalse(onboarding_response_json["onboarded"])
        self.assertEqual(len(onboarding_response_json["packages"]), 1)

        self.assertEqual(len(onboarding_response_json["questions"]), 3)

        # Answer Questions
        General.create_attribute(self.question_one, consumer=self.consumer)
        General.create_attribute(self.question_two, consumer=self.consumer)
        General.create_attribute(self.question_three, consumer=self.consumer)

        onboarding_response = self._get(self.consumer_access_token)

        self.assertEqual(onboarding_response.status_code, status.HTTP_200_OK)

        onboarding_response_json = onboarding_response.json
        self.assertFalse(onboarding_response_json["onboarded"])

        self.assertIsNotNone(onboarding_response_json["questions"][0]["attribute"])
        self.assertIsNotNone(onboarding_response_json["questions"][1]["attribute"])
        self.assertIsNotNone(onboarding_response_json["questions"][2]["attribute"])

        # Pay for subscription
        General.subscribe_to_paid_package(self.consumer)

        onboarding_response = self._get(self.consumer_access_token)

        self.assertEqual(onboarding_response.status_code, status.HTTP_200_OK)

        onboarding_response_json = onboarding_response.json
        self.assertTrue(onboarding_response_json["onboarded"])

    def test_social_auth_update_dob_as_onboarding_question(self):
        from ...question.models import Question
        from ...utils import Constants

        self.consumer = Auth.social_login(provider="apple")
        self.consumer_access_token = Auth.get_consumer_access_token(self.consumer)

        onboarding_response = self._get(self.consumer_access_token)

        self.assertEqual(onboarding_response.status_code, status.HTTP_200_OK)

        onboarding_response_json = onboarding_response.json
        self.assertFalse(onboarding_response_json["onboarded"])
        self.assertEqual(len(onboarding_response_json["packages"]), 1)

        self.assertEqual(len(onboarding_response_json["questions"]), 4)

        # Answer 'fake' DOB question
        dob_question = Question(id=Constants.QUESTION_ID_DOB)

        dob_answer_response = General.create_attribute(dob_question, value="2000-01-10", consumer=self.consumer, object_response=False)
        self.assertEqual(dob_answer_response.status_code, status.HTTP_201_CREATED)
        self.consumer.refresh_from_db()
        self.assertIsNotNone(self.consumer.date_of_birth)

        # Answer 'actual' Questions
        General.create_attribute(self.question_one, consumer=self.consumer)
        General.create_attribute(self.question_two, consumer=self.consumer)
        General.create_attribute(self.question_three, consumer=self.consumer)

        onboarding_response = self._get(self.consumer_access_token)

        self.assertEqual(onboarding_response.status_code, status.HTTP_200_OK)

        onboarding_response_json = onboarding_response.json
        self.assertFalse(onboarding_response_json["onboarded"])

        self.assertIsNotNone(onboarding_response_json["questions"][0]["attribute"])
        self.assertIsNotNone(onboarding_response_json["questions"][1]["attribute"])
        self.assertIsNotNone(onboarding_response_json["questions"][2]["attribute"])

        # Pay for subscription
        General.subscribe_to_paid_package(self.consumer)

        onboarding_response = self._get(self.consumer_access_token)

        self.assertEqual(onboarding_response.status_code, status.HTTP_200_OK)

        onboarding_response_json = onboarding_response.json
        self.consumer.refresh_from_db()
        self.assertTrue(onboarding_response_json["onboarded"])

    def test_fail_social_auth_with_invalid_dob_as_onboarding_question(self):
        from ...question.models import Question
        from ...utils import Constants

        self.consumer = Auth.social_login(provider="apple")
        self.consumer_access_token = Auth.get_consumer_access_token(self.consumer)

        onboarding_response = self._get(self.consumer_access_token)

        self.assertEqual(onboarding_response.status_code, status.HTTP_200_OK)

        onboarding_response_json = onboarding_response.json
        self.assertFalse(onboarding_response_json["onboarded"])
        self.assertEqual(len(onboarding_response_json["packages"]), 1)

        self.assertEqual(len(onboarding_response_json["questions"]), 4)

        dob_question = Question(id=Constants.QUESTION_ID_DOB)
        dob_invalid_format_answer_response = General.create_attribute(
            question=dob_question,
            value="dob",
            consumer=self.consumer,
            object_response=False
        )
        self.assertEqual(dob_invalid_format_answer_response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(dob_invalid_format_answer_response.data["value"], "'dob' is not a valid data in format 'YYYY-MM-DD")

        dob_invalid_age_answer_response = General.create_attribute(
            question=dob_question,
            value="2018-01-10",
            consumer=self.consumer,
            object_response=False
        )
        self.assertEqual(dob_invalid_age_answer_response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(dob_invalid_age_answer_response.data["value"], f"must be at least {Constants.CONSUMER_MINIMUM_AGE}")

        self.consumer.refresh_from_db()
        self.assertIsNone(self.consumer.date_of_birth)

