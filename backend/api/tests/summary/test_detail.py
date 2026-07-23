from rest_framework import status

from freezegun import freeze_time

from ..utils import Data
from ..utils.manager import General, Auth
from ...session.models import Session
from ...tasks import update_chat_summary
from ...tests.TestCase import TestCase
from ...utils import DateUtils
from ...utils.Agent import GeneralResponse, PROMPT_DATE_FORMAT
from ...utils.S3 import download_text


class CreateTest(TestCase):

    def _get(self, id_, access_token="", **kwargs):
        response = super()._get(f"/summaries/{id_}", access_token=access_token)
        return response

    def _valid_message_data(self, text: str) -> dict:
        return Data.valid_message_data(text=text, session=self.session)

    def _mocked_bot_response(self, text: str = "Sorry to hear that"):
        return GeneralResponse(
            text=text,
            reasoning="Unified Protocol",
            suggested_responses=[],
            asset_id=None
        )

    def test_basic(self):

        with freeze_time(DateUtils.yesterday().date()):
            self.consumer = Auth.create_consumer()

            self.session = General.create_session(consumer=self.consumer)
            self.message_one = General.create_message_with_mock_ai(
                consumer=self.consumer,
                data=self._valid_message_data(
                    text="Hi, I'm going through a divorce with my husband and it's starting to affect my work"
                ),
                mocked_bot_response=self._mocked_bot_response(),
            )[0]

            self.message_two = General.create_message_with_mock_ai(
                consumer=self.consumer,
                data=self._valid_message_data(
                    text="I lose focus in work really easy as I keep think about how our kids will turn out"
                ),
                mocked_bot_response=self._mocked_bot_response(),
            )[0]

        summary = self.consumer.summary

        self.assertIsNone(summary.detailed)

        self.assertIsNone(summary.observations)

        self.assertIsNone(summary.next_steps)

        update_chat_summary(self.consumer.user_id)

        summary.refresh_from_db()

        self.assertIsNotNone(summary.detailed)

        self.assertIsNotNone(summary.observations)

        self.assertIsNotNone(summary.next_steps)

    def test_chat_log_file_created_with_expected_text(self):
        yesterday = DateUtils.yesterday().date()
        with freeze_time(yesterday):
            self.consumer = Auth.create_consumer()

            self.session = General.create_session(consumer=self.consumer)
            self.message_one = General.create_message_with_mock_ai(
                consumer=self.consumer,
                data=self._valid_message_data(
                    text="Hi, I'm going through a divorce with my husband and it's starting to affect my work"
                ),
                mocked_bot_response=self._mocked_bot_response(),
            )[0]

            self.message_two = General.create_message_with_mock_ai(
                consumer=self.consumer,
                data=self._valid_message_data(
                    text="I lose focus in work really easy as I keep think about how our kids will turn out"
                ),
                mocked_bot_response=self._mocked_bot_response(),
            )[0]

        log_path = f"consumers/{self.consumer.user_id}/chat_log.txt"

        update_chat_summary(self.consumer.user_id)

        log_file = download_text(key=log_path)

        expected_text = (
            f"\n\n{yesterday:{PROMPT_DATE_FORMAT}}: Session #1 - General\n"
            f"\t\t{self.consumer.user.first_name}: Hi, I'm going through a divorce with my husband and it's starting to affect my work\n"
            "\t\tYOU: Sorry to hear that\n"
            f"\t\t{self.consumer.user.first_name}: I lose focus in work really easy as I keep think about how our kids will turn out\n"
            "\t\tYOU: Sorry to hear that\n"
        )
        self.assertEqual(log_file.strip(), expected_text.strip(), "Log file content did not match expected text")

    def test_chat_log_appended_on_next_day(self):
        day_before_yesterday = DateUtils.day_before_yesterday().date()
        with freeze_time(day_before_yesterday):
            self.consumer = Auth.create_consumer()

            self.session = General.create_session(consumer=self.consumer)
            self.message_one = General.create_message_with_mock_ai(
                consumer=self.consumer,
                data=self._valid_message_data(
                    text="Hi, I'm going through a divorce with my husband and it's starting to affect my work"
                ),
                mocked_bot_response=self._mocked_bot_response(),
            )[0]

            self.message_two = General.create_message_with_mock_ai(
                consumer=self.consumer,
                data=self._valid_message_data(
                    text="I lose focus in work really easy as I keep think about how our kids will turn out"
                ),
                mocked_bot_response=self._mocked_bot_response(),
            )[0]

        log_path = f"consumers/{self.consumer.user.id}/chat_log.txt"

        yesterday = DateUtils.yesterday().date()
        freezer = freeze_time(yesterday)
        freezer.start()

        update_chat_summary(self.consumer.user_id, freezer)

        freezer.stop()
        initial_content = download_text(key=log_path)
        expected_text = (
            f"\n\n{day_before_yesterday:{PROMPT_DATE_FORMAT}}: Session #1 - General\n"
            f"\t\t{self.consumer.user.first_name}: Hi, I'm going through a divorce with my husband and it's starting to affect my work\n"
            "\t\tYOU: Sorry to hear that\n"
            f"\t\t{self.consumer.user.first_name}: I lose focus in work really easy as I keep think about how our kids will turn out\n"
            "\t\tYOU: Sorry to hear that\n"
        )
        self.assertEqual(initial_content.strip(), expected_text.strip(), "Log file content did not match expected text")

        with freeze_time(yesterday):
            self.session = General.create_session(consumer=self.consumer)
            General.create_message_with_mock_ai(
                consumer=self.consumer,
                data=self._valid_message_data(text="Today I feel better."),
                mocked_bot_response=self._mocked_bot_response(text="That's great!"),
            )

        freezer = freeze_time(DateUtils.today().date())
        freezer.start()

        update_chat_summary(self.consumer.user_id, freezer)

        freezer.stop()

        content = download_text(key=log_path)

        self.assertIn(initial_content.strip(), content.strip())
        self.assertIn(f"{yesterday:{PROMPT_DATE_FORMAT}}", content)
        self.assertIn("Today I feel better.", content)

    def test_summary_changes_on_subsequent_day(self):
        date = DateUtils.day_before_yesterday().date()
        with freeze_time(date):
            self.consumer = Auth.create_consumer()
            self.session = General.create_session(consumer=self.consumer)

            General.create_message_with_mock_ai(
                consumer=self.consumer,
                data=self._valid_message_data(text="I feel anxious."),
                mocked_bot_response=self._mocked_bot_response(text="I'm here to listen."),
            )

        log_path = f"consumers/{self.consumer.user.id}/chat_log.txt"

        summary = self.consumer.summary

        self.assertIsNone(summary.detailed)

        self.assertIsNone(summary.observations)

        freezer = freeze_time(DateUtils.yesterday().date())
        freezer.start()

        update_chat_summary(self.consumer.user_id, freezer)

        freezer.stop()

        summary.refresh_from_db()

        old_detailed = summary.detailed
        old_observations = summary.observations

        initial_content = download_text(key=log_path)

        self.assertIn("I feel anxious.", initial_content)

        yesterday = DateUtils.yesterday().date()
        with freeze_time(yesterday):
            # New session, updated mood
            self.session = General.create_session(consumer=self.consumer)
            General.create_message_with_mock_ai(
                consumer=self.consumer,
                data=self._valid_message_data(text="Feeling much more hopeful now."),
                mocked_bot_response=self._mocked_bot_response(text="That's a positive change!"),
            )

        freezer = freeze_time(DateUtils.today().date())
        freezer.start()

        update_chat_summary(self.consumer.user_id, freezer)

        freezer.stop()

        updated_content = download_text(key=log_path)

        summary.refresh_from_db()

        new_detailed = summary.detailed
        new_observations = summary.observations

        # Make sure old summary content exists, but new day's messages are also present
        self.assertIn("I feel anxious.", updated_content)
        self.assertIn("Feeling much more hopeful now.", updated_content)

        self.assertNotEqual(old_detailed, new_detailed, "Summary details should have changed.")
        self.assertNotEqual(old_observations, new_observations, "Summary observations should have changed.")

    def test_summary_includes_topic(self):
        with freeze_time(DateUtils.yesterday().date()):
            self.consumer = Auth.create_consumer()
            self.session = General.create_session(consumer=self.consumer)

            self.message_one = General.create_message_with_mock_ai(
                consumer=self.consumer,
                data=self._valid_message_data(
                    text="I've been stressed about work deadlines."
                ),
                mocked_bot_response=self._mocked_bot_response(
                    "That sounds tough. Let’s explore how you can manage stress."
                ),
            )[0]

            self.message_two = General.create_message_with_mock_ai(
                consumer=self.consumer,
                data=self._valid_message_data(
                    text="I feel better when I break tasks into smaller pieces."
                ),
                mocked_bot_response=self._mocked_bot_response(
                    "That’s a great strategy to reduce overwhelm."
                ),
            )[0]

        update_chat_summary(self.consumer.user_id)
        summary = self.consumer.summary
        summary.refresh_from_db()

        session = Session.objects.get(id=self.session.id)

        self.assertIsNotNone(session.subject)
        self.assertNotIn(self.consumer.user.first_name, session.subject)
        self.assertLessEqual(len(session.subject.split()), 10)
        self.assertIn("stress", session.subject.lower())

    def test_summary_includes_rating(self):
        with freeze_time(DateUtils.yesterday().date()):
            self.consumer = Auth.create_consumer()
            self.session = General.create_session(consumer=self.consumer)

            self.message = General.create_message_with_mock_ai(
                consumer=self.consumer,
                data=self._valid_message_data(
                    text="I'm feeling anxious about an upcoming exam."
                ),
                mocked_bot_response=self._mocked_bot_response(
                    "I hear you. Let's try a calming breathing exercise."
                ),
            )[0]

        update_chat_summary(self.consumer.user_id)
        summary = self.consumer.summary
        summary.refresh_from_db()

        session = Session.objects.get(id=self.session.id)

        self.assertIsNotNone(session.rating)
        self.assertIsNotNone(session.rating_reason)
        self.assertGreaterEqual(session.rating, 0.0)
        self.assertLessEqual(session.rating, 10.0)

    def test_summary_includes_risk_level_low(self):
        with freeze_time(DateUtils.yesterday().date()):
            self.consumer = Auth.create_consumer()
            self.session = General.create_session(consumer=self.consumer)

            self.message = General.create_message_with_mock_ai(
                consumer=self.consumer,
                data=self._valid_message_data(
                    text="I've been feeling down lately but trying to cope."
                ),
                mocked_bot_response=self._mocked_bot_response(
                    "Thanks for sharing. It's important to acknowledge these feelings."
                ),
            )[0]
        summary = self.consumer.summary
        self.assertIsNone(self.session.risk_level)

        update_chat_summary(self.consumer.user_id)

        summary.refresh_from_db()

        session = Session.objects.get(id=self.session.id)

        self.assertIsNotNone(session.risk_level)
        self.assertEqual(session.risk_level, "low")

    def test_summary_includes_risk_level_high(self):
        with freeze_time(DateUtils.yesterday().date()):
            self.consumer = Auth.create_consumer()
            self.session = General.create_session(consumer=self.consumer)

            self.message = General.create_message_with_mock_ai(
                consumer=self.consumer,
                data=self._valid_message_data(
                    text="Sometimes I think about ending everything."
                ),
                mocked_bot_response=self._mocked_bot_response(
                    "I’m really concerned about your safety. It sounds serious."
                ),
            )[0]
        summary = self.consumer.summary
        self.assertIsNone(self.session.risk_level)

        update_chat_summary(self.consumer.user_id)

        summary.refresh_from_db()

        session = Session.objects.get(id=self.session.id)

        self.assertIsNotNone(session.risk_level)
        self.assertEqual(session.risk_level, "high")

    def test_admin(self):
        admin_access_token = Auth.get_platform_admin_access_token()
        consumer = Auth.create_consumer()

        response = self._get(consumer.user_id, access_token=admin_access_token)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["consumer"], consumer.user_id)

    def test_fail_consumer(self):
        consumer = Auth.create_consumer()

        self.permission_denied_test(self._get(consumer.user_id, access_token=Auth.get_access_token(consumer.user)))

    def test_fail_unauthenticated(self):
        consumer = Auth.create_consumer()

        self.unauthorized_account_test(self._get(consumer.user_id, access_token=""))
