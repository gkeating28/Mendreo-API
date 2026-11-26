import inspect
from datetime import datetime, timezone as dt_timezone
from types import SimpleNamespace

from django.test import SimpleTestCase
from django.utils import timezone
from rest_framework import status

from ..utils.BaseTest import BaseTest
from ..utils.manager import General
from ..TestCase import TestCase
from ...message.models import Message
from ...participant.models import Participant
from ...session.models import Session, SessionStep
from ...run import services as run_services


def _at(minute: int):
    return datetime(2026, 9, 25, 11, minute, tzinfo=dt_timezone.utc)


def _chat(text, *, minute, guide=True, label="", id="msg_guide"):
    sender = SimpleNamespace(consumer_id=None if guide else "user")
    return SimpleNamespace(
        id=id,
        text=text,
        created_at=_at(minute),
        sender=sender,
        completion_label=label,
    )


class RunServicesImportTests(SimpleTestCase):
    def test_does_not_import_agent_at_module_level(self):
        source = inspect.getsource(run_services)
        self.assertNotIn("utils.Agent", source)
        self.assertIn("utils.completion", source)

    def test_transcript_buckets_follow_completion_labels(self):
        check_in = _chat("Welcome back.", minute=0)
        thread = [
            check_in,
            _chat("What is the worry?", minute=2, id="msg_worry"),
            _chat("Getting fired", minute=3, guide=False, id="msg_fired"),
            _chat(
                "Are you ready to continue?",
                minute=5,
                label="You have described it",
                id="msg_ready",
            ),
            _chat("Yes, I'm ready", minute=6, guide=False, id="msg_yes"),
            _chat("What time of day?", minute=7, id="msg_time"),
            _chat("Mornings", minute=8, guide=False, id="msg_mornings"),
            _chat("Ready to finish?", minute=9, label="The plan is set", id="msg_finish"),
            _chat("Finish exercise", minute=10, guide=False, id="msg_done"),
        ]
        buckets = run_services._transcript_buckets(
            thread,
            check_in_completed_at=_at(1),
        )
        self.assertEqual(
            [item["text"] for item in buckets[1]],
            [
                "What is the worry?",
                "Getting fired",
                "Are you ready to continue?",
                "Yes, I'm ready",
            ],
        )
        self.assertEqual(
            [item["text"] for item in buckets[2]],
            [
                "What time of day?",
                "Mornings",
                "Ready to finish?",
                "Finish exercise",
            ],
        )
        self.assertNotIn(3, buckets)
        self.assertNotIn("Welcome back.", [item["text"] for item in buckets[1]])
        self.assertEqual(
            [item["id"] for item in buckets[1] if item["role"] == "guide"],
            ["msg_worry", "msg_ready"],
        )
        self.assertEqual(
            [item["id"] for item in buckets[2] if item["role"] == "guide"],
            ["msg_time", "msg_finish"],
        )
        for bucket in buckets.values():
            for item in bucket:
                self.assertEqual(set(item) - {"id"}, {"role", "text"})
                if item["role"] == "user":
                    self.assertNotIn("id", item)
                else:
                    self.assertIn("id", item)


class ReflectRunApiTests(BaseTest):
    def endpoint(self):
        return "runs"

    def _complete_run(self, finding="The team restructure in October"):
        exercise = General.create_exercise()
        session = Session.objects.create(
            consumer=self.consumer_one,
            exercise=exercise,
            completed=True,
            current_step_no=exercise.steps_no,
            total_steps_no=exercise.steps_no,
        )
        SessionStep.create(session, exercise)
        Session.objects.filter(id=session.id).update(
            completed_at=timezone.now(),
            updated_at=timezone.now(),
        )
        session.refresh_from_db()
        consumer_pt, agent_pt = Participant.create_participants(session)
        step = session.session_steps.order_by("order").first()
        if step:
            step.completed = True
            step.completion_result = finding
            step.save(update_fields=["completed", "completion_result", "updated_at"])
        first = Message.objects.create(session=session, sender=agent_pt, text="What's the worry?")
        second = Message.objects.create(session=session, sender=consumer_pt, text=finding)
        Message.objects.filter(id=first.id).update(step_no=1)
        Message.objects.filter(id=second.id).update(step_no=1)
        return session, exercise

    def test_list_completed_runs_and_save_reflection(self):
        session, exercise = self._complete_run()
        listed = TestCase._get(
            "/runs",
            query_params_dict={"status": "completed"},
            access_token=self.consumer_one_access_token,
        )
        self.assertEqual(listed.status_code, status.HTTP_200_OK, listed.json)
        self.assertEqual(listed.json["count"], 1)
        run = listed.json["results"][0]
        self.assertEqual(run["id"], session.id)
        self.assertEqual(run["exerciseId"], exercise.id)
        self.assertEqual(run["topic"], "The team restructure in October")
        self.assertEqual(run["basis"], "Work")
        self.assertFalse(run["steps"][0].get("transcript"))

        detail = TestCase._get(
            f"/runs/{session.id}",
            access_token=self.consumer_one_access_token,
        )
        self.assertEqual(detail.status_code, status.HTTP_200_OK, detail.json)
        transcript = detail.json["steps"][0]["transcript"]
        self.assertGreaterEqual(len(transcript), 1)
        guide_message = Message.objects.get(session=session, text="What's the worry?")
        guide = next(item for item in transcript if item["role"] == "guide")
        user = next(item for item in transcript if item["role"] == "user")
        self.assertEqual(guide["id"], guide_message.id)
        self.assertEqual(guide["text"], "What's the worry?")
        self.assertEqual(set(guide), {"role", "text", "id"})
        self.assertEqual(set(user), {"role", "text"})

        step_id = detail.json["steps"][0]["stepId"]
        saved = TestCase._put(
            f"/runs/{session.id}/reflections/{step_id}",
            {"text": "It still shows up on Sunday nights."},
            access_token=self.consumer_one_access_token,
        )
        self.assertEqual(saved.status_code, status.HTTP_200_OK, getattr(saved, "json", saved))
        self.assertEqual(saved.json["stepId"], step_id)
        self.assertIn("Sunday", saved.json["text"])

        again = TestCase._get(
            f"/runs/{session.id}",
            access_token=self.consumer_one_access_token,
        )
        self.assertEqual(len(again.json["reflections"]), 1)

        cleared = TestCase._put(
            f"/runs/{session.id}/reflections/{step_id}",
            {"text": "  "},
            access_token=self.consumer_one_access_token,
        )
        self.assertEqual(cleared.status_code, status.HTTP_200_OK, cleared.json)
        empty = TestCase._get(
            f"/runs/{session.id}",
            access_token=self.consumer_one_access_token,
        )
        self.assertEqual(empty.json["reflections"], [])

    def test_in_progress_runs_are_hidden(self):
        exercise = General.create_exercise()
        Session.objects.create(
            consumer=self.consumer_one,
            exercise=exercise,
            completed=False,
            current_step_no=1,
            total_steps_no=exercise.steps_no,
        )
        listed = TestCase._get(
            "/runs",
            query_params_dict={"status": "completed"},
            access_token=self.consumer_one_access_token,
        )
        self.assertEqual(listed.status_code, status.HTTP_200_OK, listed.json)
        self.assertEqual(listed.json["count"], 0)
