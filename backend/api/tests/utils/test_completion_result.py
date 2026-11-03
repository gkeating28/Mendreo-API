from unittest import mock

from django.test import SimpleTestCase

from ...knowledge.models import KnowledgeField
from ...message.models import Message
from ...participant.models import Participant
from ...session.models import Session, SessionStep
from ...tests.TestCase import TestCase
from ...utils.Agent import SKIP_COMPLETION_RESULT, coerce_completion_result
from ...utils.completion import (
    is_usable_completion_result,
    pick_completion_result_from_texts,
    strip_trailing_readiness_phrase,
)
from ...utils.extraction import extract_step_result
from ..utils.manager import Auth, General


class CompletionResultTextTests(SimpleTestCase):
    def test_rejects_placeholders_and_confirmations(self):
        for value in [
            None,
            "",
            "   ",
            "N/A",
            "n/a",
            "na",
            "None",
            "yes",
            "Yes!",
            "ok",
            "okay",
            "Step 1 completed.",
            "qa skip step",
            "User ready for Step 3.",
            "User ready for Step 3",
            "The user identified all-or-nothing thinking",
            "User provided two strong responses.",
        ]:
            self.assertFalse(is_usable_completion_result(value), msg=repr(value))

    def test_strips_a_trailing_ready_chip_from_the_finding(self):
        finding = "Worry and stress are unproductive, planning is productive."
        stripped = strip_trailing_readiness_phrase(f"{finding} Yes, I'm ready.")
        self.assertEqual(stripped, finding)
        self.assertTrue(is_usable_completion_result(stripped))
        for phrase in ("Yes, I'm ready", "Not yet", "Finish exercise"):
            self.assertEqual(
                strip_trailing_readiness_phrase(f"{finding} {phrase}"),
                finding,
            )
        self.assertEqual(
            strip_trailing_readiness_phrase(
                "Worry and stress are unproductive, planning is productive; Yes, I'm ready"
            ),
            "Worry and stress are unproductive, planning is productive",
        )

    def test_accepts_named_worry(self):
        self.assertTrue(is_usable_completion_result("I'll lose my job if I speak up"))
        self.assertTrue(is_usable_completion_result("7"))

    def test_picks_worry_not_the_yes(self):
        self.assertEqual(
            pick_completion_result_from_texts(
                ["Yes", "I'll lose my job if I speak up", "hi"]
            ),
            "I'll lose my job if I speak up",
        )

    @mock.patch("api.utils.Agent.consumer_texts_for_current_step")
    def test_coerce_recovers_from_na(self, mock_texts):
        mock_texts.return_value = ["Yes", "I'm worried I'll fail the exam"]
        result = coerce_completion_result(
            completion_result="N/A",
            is_step_complete=True,
            session=object(),
            user_message=None,
        )
        self.assertEqual(result, "I'm worried I'll fail the exam")

    def test_coerce_keeps_skip_and_real_answers(self):
        self.assertEqual(
            coerce_completion_result(
                completion_result=SKIP_COMPLETION_RESULT,
                is_step_complete=True,
                session=object(),
            ),
            SKIP_COMPLETION_RESULT,
        )
        self.assertEqual(
            coerce_completion_result(
                completion_result="I'll lose my job",
                is_step_complete=True,
                session=object(),
            ),
            "I'll lose my job",
        )
        self.assertIsNone(
            coerce_completion_result(
                completion_result="I'll lose my job",
                is_step_complete=False,
                session=object(),
            )
        )


class CompletionResultSessionTests(TestCase):
    def setUp(self):
        self.consumer = Auth.create_consumer()
        self.exercise = General.create_exercise()
        self.session = General.start_session(
            consumer=self.consumer, exercise=self.exercise
        )
        self.consumer_pt = Participant.objects.filter(
            session=self.session, consumer=self.consumer
        ).first()
        self.agent_pt = Participant.objects.filter(
            session=self.session, agent=self.consumer.agent
        ).first()

    def test_recovers_worry_from_earlier_turn(self):
        Message.objects.create(
            session=self.session,
            sender=self.consumer_pt,
            text="I'm worried I'll fail the exam",
        )
        yes = Message.objects.create(
            session=self.session, sender=self.consumer_pt, text="Yes"
        )

        result = coerce_completion_result(
            completion_result="N/A",
            is_step_complete=True,
            session=self.session,
            user_message=yes,
        )
        self.assertEqual(result, "I'm worried I'll fail the exam")

    def test_does_not_reuse_previous_step_answer(self):
        Message.objects.create(
            session=self.session,
            sender=self.consumer_pt,
            text="worry from step 1",
        )
        Message.objects.create(
            session=self.session,
            sender=self.agent_pt,
            text="step 1 done",
            is_step_complete=True,
            completion_result="worry from step 1",
        )
        Message.objects.create(
            session=self.session,
            sender=self.consumer_pt,
            text="I parked it in a notes app",
        )
        yes = Message.objects.create(
            session=self.session, sender=self.consumer_pt, text="Yes"
        )

        result = coerce_completion_result(
            completion_result="N/A",
            is_step_complete=True,
            session=self.session,
            user_message=yes,
        )
        self.assertEqual(result, "I parked it in a notes app")


class ExtractionChipTests(TestCase):
    def _session(self, *, result_field=False):
        consumer = Auth.create_consumer()
        exercise = General.create_exercise()
        step = exercise.steps.order_by("order").first()
        step.completion_prompt = "Summarise the step."
        if result_field:
            step.result_field = KnowledgeField.objects.create(
                key=f"answer_{exercise.id}",
                label="Answer",
                category="Worry",
                active=True,
            )
        step.save(update_fields=["completion_prompt", "result_field", "updated_at"])
        session = Session.objects.create(
            consumer=consumer,
            exercise=exercise,
            current_step_no=1,
            total_steps_no=1,
        )
        SessionStep.objects.create(session=session, step=step, order=0, completed=False)
        Participant.create_participants(session)
        return session, step

    @mock.patch("api.utils.extraction._write_result_knowledge")
    @mock.patch("api.utils.extraction.AI.ask", return_value={"value": "Yes, I'm ready", "confidence": 0.9})
    def test_free_text_ready_chip_is_null(self, ask, _write):
        session, step = self._session()
        extracted = extract_step_result(session, step)
        self.assertIsNone(extracted["value"])
        self.assertEqual(extracted["confidence"], 0.0)
        ask.assert_called_once()

    @mock.patch("api.utils.extraction._write_result_knowledge")
    @mock.patch("api.utils.extraction.AI.ask", return_value={"value": "yes", "confidence": 0.8})
    def test_result_field_keeps_yes(self, _ask, _write):
        session, step = self._session(result_field=True)
        extracted = extract_step_result(session, step)
        self.assertEqual(extracted["value"], "yes")
        self.assertEqual(extracted["confidence"], 0.8)
