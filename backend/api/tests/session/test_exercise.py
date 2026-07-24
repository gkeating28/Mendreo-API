from django.utils import timezone
from freezegun import freeze_time

from ..utils import Data
from ..utils.manager import General, Auth
from ...session.models import Session
from ...tests.TestCase import TestCase
from ...utils.Agent import GeneralResponse, ExerciseResponse


class ExerciseTest(TestCase):

    def setUp(self):
        self.consumer = Auth.create_consumer()

        self.exercise = General.create_exercise()

        self.session = General.start_session(consumer=self.consumer, exercise=self.exercise)

    def _valid_message_data(self, text: str) -> dict:
        return Data.valid_message_data(text=text, session=self.session)

    def _mocked_bot_response(self, text: str, step: int = None, completed: bool = False):
        return ExerciseResponse(
            text=text,
            reasoning="Unified Protocol",
            suggested_responses=[],
            is_complete=completed,
            step_no=step or 1,
        )

    def _send_message(self, text, expected_session_step_no: int, expected_step_no: int = None, has_completion_result: bool = False):
        import time
        time.sleep(1)
        message = General.create_message(
            consumer=self.consumer,
            data=self._valid_message_data(text=text)
        )

        self.session.refresh_from_db()

        print("\033[92m User: ", text)
        print("\033[94m Bot:  ", message.text)
        print("")
        print("\033[93m Step:  ", message.step_no, "  Complete: ", message.is_step_complete, "    |  ", message.completion_result, message.completion_label)
        print("\033[91m Reasoning:  ", message.reasoning)
        print("")
        if has_completion_result:
            if not message.is_step_complete:
                self.assertIsNotNone(message.completion_result)
        else:
            self.assertIsNone(message.completion_result)

        self.assertEqual(message.step_no, expected_step_no or expected_session_step_no)
        self.assertEqual(self.session.current_step_no, expected_session_step_no)

        return message

    def test_full_flow(self):
        # Step 1
        self._send_message(
            text="Lets use the exact thought: I'm bad at my job, I'll try rephrase it to be more factual?",
            expected_session_step_no=1
        )

        self._send_message(
            text="Hmm, can you give me an example?",
            expected_session_step_no=1
        )

        self._send_message(
            text="I think we can rephrase it to be: I keep missing deadlines at my job, lets move on to the next step",
            expected_session_step_no=1,
            expected_step_no=1,
        )

        self._send_message(
            text="Yes",
            expected_session_step_no=2,
            expected_step_no=1,
            has_completion_result=True
        )

        self._send_message(
            text="Whats a thinking trap?",
            expected_session_step_no=2,
        )

        self._send_message(
            text="It could be a thinking trap or bias but he had a report on this. I miss the deadlines for 80% of my projects so it's factual",
            expected_session_step_no=2,
            expected_step_no=2,
        )

        self._send_message(
            text="Yes",
            expected_session_step_no=3,
            expected_step_no=2,
            has_completion_result=True
        )

        self._send_message(
            text="I know its true",
            expected_session_step_no=3,
        )

        self._send_message(
            text="It's factual, my Boss gave me a written report of all my previous estimates and actual delivery dates",
            expected_session_step_no=3,
        )

        self._send_message(
            text="I may have underestimated the work or overestimated by own capabilities",
            expected_session_step_no=3,
        )

        self._send_message(
            text="Highly likely, as these are solo projects with only me on them. Lets move on to the next step.",
            expected_session_step_no=3,
        )

        self._send_message(
            text="Sometimes extra things get added / scope shifts during the project and times are not updated",
            expected_session_step_no=3,
        )

        self._send_message(
            text="You're right, its more realistic that its due to the other factors than my initial thought, thank you very much for helping me see that",
            expected_session_step_no=3,
        )

        self._send_message(
            text="Yes",
            expected_session_step_no=3,
            has_completion_result=True
        )

        response = self._get(
            endpoint=f"/sessions/{self.session.id}/summary",
            access_token=Auth.get_consumer_access_token(self.consumer)
        )

        self.assertIsNotNone(response.json["usage"])

    def test_skip(self):
        from ...utils import Constants

        step_one_complete_message = self._send_message(
            text=Constants.MESSAGE_TEXT_SKIP_STEP,
            expected_session_step_no=2,
            expected_step_no=1,
            has_completion_result=True
        )

        self.assertIsNotNone(step_one_complete_message.completion_result, "Skipped Step")

        step_two_complete_message = self._send_message(
            text=Constants.MESSAGE_TEXT_SKIP_STEP,
            expected_session_step_no=3,
            expected_step_no=2,
            has_completion_result=True
        )

        self.assertIsNotNone(step_two_complete_message.completion_result, "Skipped Step")

        step_three_complete_message = self._send_message(
            text=Constants.MESSAGE_TEXT_SKIP_STEP,
            expected_session_step_no=3,
            expected_step_no=3,
            has_completion_result=True
        )
        
        self.assertIsNotNone(step_three_complete_message.completion_result, "Skipped Step")

        response = self._get(
            endpoint=f"/sessions/{self.session.id}/summary",
            access_token=Auth.get_consumer_access_token(self.consumer)
        )

        self.assertIsNotNone(response.json["usage"])

        self.exercise.refresh_from_db()
        self.assertEqual(self.exercise.completions_no, 1)

    def test_summary(self):
        # Step 1
        self._send_message(
            text="Lets use the exact thought: I'm bad at my job, I'll try rephrase it to be more factual?",
            expected_session_step_no=1
        )

        self.session.completed = True
        self.session.save()

        response = self._get(
            endpoint=f"/sessions/{self.session.id}/summary",
            access_token=Auth.get_consumer_access_token(self.consumer)
        )

    def test_asset(self):
        from ...utils import Constants
        from ...asset.models import Asset
        from ..utils.manager import General

        file = General.create_file()
        post = General.create_post()
        image = General.create_image()

        session_step = self.session.session_steps.filter(order=0).first()

        Asset.objects.create(file=file, context="File")
        Asset.objects.create(post=post, context="Post")
        Asset.objects.create(image=image, context="Image")

        text_message = self._send_message(
            text="Hello",
            expected_session_step_no=1,
        )

        self.assertIsNone(text_message.asset)

        self.session.refresh_from_db()
        session_step.refresh_from_db()
        self.assertIsNone(self.session.last_asset_id)
        self.assertIsNone(session_step.last_asset_id)

        file_message = self._send_message(
            text=Constants.MESSAGE_TEXT_ASSET_FILE,
            expected_session_step_no=1,
        )

        self.assertIsNotNone(file_message.asset.file)

        self.session.refresh_from_db()
        session_step.refresh_from_db()
        self.assertEqual(self.session.last_asset_id, file_message.asset_id)
        self.assertEqual(session_step.last_asset_id, file_message.asset_id)

        post_message = self._send_message(
            text=Constants.MESSAGE_TEXT_ASSET_POST,
            expected_session_step_no=1,
        )

        self.assertIsNotNone(post_message.asset.post)

        self.session.refresh_from_db()
        session_step.refresh_from_db()
        self.assertEqual(self.session.last_asset_id, post_message.asset_id)
        self.assertEqual(session_step.last_asset_id, post_message.asset_id)

        image_message = self._send_message(
            text=Constants.MESSAGE_TEXT_ASSET_IMAGE,
            expected_session_step_no=1,
        )

        self.assertIsNotNone(image_message.asset.image)

        self.session.refresh_from_db()
        session_step.refresh_from_db()
        self.assertEqual(self.session.last_asset_id, image_message.asset_id)
        self.assertEqual(session_step.last_asset_id, image_message.asset_id)

        text_message = self._send_message(
            text="Hello",
            expected_session_step_no=1,
        )

        self.assertIsNone(text_message.asset)

        self.session.refresh_from_db()
        session_step.refresh_from_db()
        self.assertEqual(self.session.last_asset_id, image_message.asset_id)
        self.assertEqual(session_step.last_asset_id, image_message.asset_id)

    def test_triage(self):
        from ...utils import Constants
        from ..utils.manager import General

        self.exercise.status = Constants.EXERCISE_STATUS_PUBLISHED
        self.exercise.save()

        self.session = General.start_session(consumer=self.consumer)

        text_message = General.create_message(
            consumer=self.consumer,
            data=self._valid_message_data(text="Hello")
        )

        self.assertIsNone(text_message.exercise)

        exercise_prompt = General.create_message(
            consumer=self.consumer,
            data=self._valid_message_data(text=Constants.MESSAGE_TEXT_EXERCISE)
        )

        self.assertIsNotNone(exercise_prompt.exercise)

        exercise_prompt = General.create_message(
            consumer=self.consumer,
            data=self._valid_message_data(text=f"Lets do the {self.exercise.title} exercise")
        )

        self.assertIsNotNone(exercise_prompt.exercise)

        self.exercise.delete()

        exercise_prompt = General.create_message(
            consumer=self.consumer,
            data=self._valid_message_data(text=Constants.MESSAGE_TEXT_EXERCISE)
        )

        self.assertIsNone(exercise_prompt.exercise)

