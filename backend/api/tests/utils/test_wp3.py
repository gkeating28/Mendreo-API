from unittest.mock import patch

from rest_framework import status

from ...attribute.serializers import AttributeCreateSerializer
from ...knowledge.models import KnowledgeEntry, KnowledgeField, KnowledgeQuestion
from ...message.models import Message
from ...onboarding.services import submit_flow_answers
from ...participant.models import Participant
from ...question.models import Question
from ...session.models import Session, SessionMetric
from ...setting.models import Setting
from ...utils import Constants
from ...utils.history import build_history
from ...utils.risk import apply_turn_risk
from ...utils.turn_hint import (
    ACCEPT_HINT,
    FOLLOW_UP_HINT,
    entry_quality,
    generic_answers_for,
    probe_count_for,
    shape_chips,
    turn_hint_text,
    user_prompt_with_hint,
)
from ..TestCase import TestCase
from ..utils.manager import Auth


class _Previous:
    def __init__(self, question_kind, probe_count=0):
        self.question_kind = question_kind
        self.probe_count = probe_count


class Wp3Tests(TestCase):
    def test_history_keeps_recent_turns_and_summarises_the_rest(self):
        setting = Setting.get_or_create_history_max_turns()
        setting.value = "2"
        setting.save()

        consumer = Auth.create_consumer()
        session = Session.objects.create(consumer=consumer)
        user_sender, agent_sender = Participant.create_participants(session)
        for index in range(3):
            Message.objects.create(session=session, sender=user_sender, text=f"user {index}")
            Message.objects.create(session=session, sender=agent_sender, text=f"agent {index}")
        current = Message.objects.create(
            session=session, sender=user_sender, text="current question"
        )

        with patch(
            "api.utils.history.AI.ask",
            return_value={"summary": "Earlier tension."},
        ) as ask:
            history = build_history(session, exclude_message_id=current.id)
            again = build_history(session, exclude_message_id=current.id)

        self.assertEqual(ask.call_count, 1)
        self.assertEqual(ask.call_args.kwargs["temperature"], 0.2)
        self.assertIn("user 0", ask.call_args.args[0])

        text = " ".join(part.content for message in history for part in message.parts)
        self.assertIn("Earlier tension.", text)
        self.assertIn("user 1", text)
        self.assertIn("user 2", text)
        self.assertNotIn("user 0", text)
        self.assertNotIn("current question", text)
        self.assertEqual(len(again), len(history))
        session.refresh_from_db()
        self.assertEqual(session.history_summary, "Earlier tension.")

    def test_turn_hints_and_open_chips(self):
        self.assertIn(
            "sentence starters the user completes",
            Constants.PROMPT_PROGRAMMING_INSTRUCTIONS,
        )
        open_question = _Previous(Constants.QUESTION_KIND_OPEN, 0)
        self.assertEqual(turn_hint_text(open_question, "yes"), FOLLOW_UP_HINT)
        self.assertIn("One question only.", FOLLOW_UP_HINT)
        self.assertEqual(
            turn_hint_text(_Previous(Constants.QUESTION_KIND_OPEN, 1), "fine"),
            FOLLOW_UP_HINT,
        )
        self.assertEqual(
            turn_hint_text(_Previous(Constants.QUESTION_KIND_OPEN, 2), "ok"),
            ACCEPT_HINT,
        )
        self.assertIsNone(
            turn_hint_text(_Previous(Constants.QUESTION_KIND_CLOSED, 0), "yes")
        )
        self.assertIsNone(
            turn_hint_text(_Previous(Constants.QUESTION_KIND_NONE, 0), "yes")
        )
        self.assertEqual(probe_count_for(open_question, Constants.QUESTION_KIND_OPEN), 1)
        self.assertEqual(probe_count_for(open_question, Constants.QUESTION_KIND_CLOSED), 0)
        self.assertEqual(
            probe_count_for(_Previous(Constants.QUESTION_KIND_CLOSED), Constants.QUESTION_KIND_OPEN),
            0,
        )

        shaped = shape_chips(
            ["fine", "I was at home", "When I noticed it", "Tonight"],
            Constants.QUESTION_KIND_OPEN,
        )
        self.assertEqual(shaped, ["I was at home...", "When I noticed it..."])
        self.assertEqual(
            shape_chips(["Yes", "No"], Constants.QUESTION_KIND_CLOSED),
            ["Yes", "No"],
        )

        consumer = Auth.create_consumer()
        session = Session.objects.create(consumer=consumer)
        user_sender, agent_sender = Participant.create_participants(session)
        Message.objects.create(
            session=session,
            sender=agent_sender,
            text="What happened?",
            question_kind=Constants.QUESTION_KIND_OPEN,
            probe_count=0,
        )
        user_message = Message.objects.create(
            session=session, sender=user_sender, text="yes"
        )
        prompted = user_prompt_with_hint(session, user_message)
        self.assertIn("<TURN_HINT>", prompted)
        self.assertIn("One question only.", prompted)
        self.assertNotIn("<TURN_HINT>", user_message.text)

        closed = Message.objects.create(
            session=session,
            sender=agent_sender,
            text="Ready?",
            question_kind=Constants.QUESTION_KIND_CLOSED,
            probe_count=0,
        )
        closed_user = Message.objects.create(
            session=session, sender=user_sender, text="yes"
        )
        self.assertEqual(user_prompt_with_hint(session, closed_user), "yes")
        self.assertEqual(closed.question_kind, Constants.QUESTION_KIND_CLOSED)

    def test_high_risk_sets_resources_and_queues_notification(self):
        consumer = Auth.create_consumer()
        session = Session.objects.create(consumer=consumer)

        with patch("api.tasks.notify_trust_and_safety.delay_on_commit") as queued:
            moderate = apply_turn_risk(session, "I might hurt myself", "none")
            self.assertIsNone(queued.call_args)
            resources = apply_turn_risk(session, "I want to die", "low")

        self.assertEqual(moderate["title"], "Support is available")
        self.assertIn("links", resources)
        session.refresh_from_db()
        self.assertEqual(session.live_risk_level, Constants.LIVE_RISK_LEVEL_HIGH)
        queued.assert_called_once_with(session.id)

        with patch("api.tasks.notify_trust_and_safety.delay_on_commit") as again:
            apply_turn_risk(session, "hello", "none")
        again.assert_not_called()
        session.refresh_from_db()
        self.assertEqual(session.live_risk_level, Constants.LIVE_RISK_LEVEL_HIGH)

    def test_numeric_form_answer_is_a_metric(self):
        consumer = Auth.create_consumer()
        consumer.onboarded = True
        consumer.save(update_fields=["onboarded"])
        session = Session.objects.create(consumer=consumer, cached_prompt="stale")
        field = KnowledgeField.objects.create(
            key="disruptiveness",
            label="Disruptiveness",
            category="Worry",
            active=True,
        )
        question = Question.objects.create(
            session=session,
            type=Constants.QUESTION_TYPE_NUMBER,
            title="How disruptive was it?",
            key="disruptiveness",
            attribute_key="disruptiveness",
            knowledge_field=field,
        )
        serializer = AttributeCreateSerializer(
            data={"value": "4", "question": question.id, "consumer": consumer.pk}
        )
        self.assertTrue(serializer.is_valid(), serializer.errors)
        serializer.save()

        metric = SessionMetric.objects.get(session=session, key="disruptiveness")
        self.assertEqual(float(metric.value), 4.0)
        self.assertEqual(metric.source, Constants.SESSION_METRIC_SOURCE_FORM)
        session.refresh_from_db()
        self.assertEqual(session.form_answers["disruptiveness"], "4")
        self.assertIsNone(session.cached_prompt)

        token = Auth.get_access_token(consumer.user)
        response = self._get("/metrics", {"keys": "disruptiveness"}, token)
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json)
        self.assertEqual(response.json[0]["label"], "Disruptiveness")
        self.assertEqual(response.json[0]["points"][0]["value"], 4.0)
        self.assertEqual(response.json[0]["points"][0]["exercise_id"], None)

    def test_onboarding_fine_is_pending_review(self):
        consumer = Auth.create_consumer()
        field = KnowledgeField.objects.create(
            key="day_word",
            label="Day word",
            category="Wellbeing",
            active=True,
        )
        question = KnowledgeQuestion.objects.create(
            prompt="How was today?",
            target_field=field,
            response_type=Constants.KNOWLEDGE_RESPONSE_TYPE_TEXT,
            flows=[Constants.KNOWLEDGE_FLOW_INITIAL],
            order=1,
            active=True,
        )
        confidence, review = entry_quality(
            "I slept badly after the meeting yesterday",
            response_type=Constants.KNOWLEDGE_RESPONSE_TYPE_TEXT,
            generic_answers=generic_answers_for(question),
        )
        self.assertEqual(confidence, 1.0)
        self.assertEqual(review, Constants.KNOWLEDGE_REVIEW_ACCEPTED)

        submit_flow_answers(
            consumer,
            variant="initial",
            answers=[{"knowledge_question_id": question.id, "value": "fine"}],
            complete=True,
            classify_vagueness=False,
        )
        entry = KnowledgeEntry.objects.get(consumer=consumer, field=field)
        self.assertEqual(entry.source, Constants.KNOWLEDGE_ENTRY_SOURCE_ONBOARDING)
        self.assertEqual(entry.confidence, Constants.THIN_ANSWER_CONFIDENCE)
        self.assertEqual(entry.review_status, Constants.KNOWLEDGE_REVIEW_PENDING)
