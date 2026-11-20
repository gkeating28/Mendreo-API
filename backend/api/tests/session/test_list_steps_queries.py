import json

from django.db import connection
from rest_framework.renderers import JSONRenderer
from django.db.models import Prefetch
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from ..utils.manager import Auth
from ...exercise.models import Exercise
from ...message.models import Message
from ...participant.models import Participant
from ...session.models import Session, SessionStep
from ...session.serializers import SessionListSerializer
from ...step.models import Step
from ...tests.TestCase import TestCase
from ...utils import Constants
from ...utils.SessionStateMachine import build_session_state
from ...utils.session_progress import session_progress


def _exercise(step_count=4, *, title="Think flexibly"):
    exercise = Exercise.objects.create(
        title=title,
        subtitle="One thought",
        description="Work through one thought.",
        status=Constants.EXERCISE_STATUS_DRAFT,
        steps_no=step_count,
        icon="leaf",
        icon_background_color="tan",
        check_in_start_button_label="Begin",
    )
    for index in range(step_count):
        Step.objects.create(
            exercise=exercise,
            title=f"Step {index + 1}",
            description="Describe it",
            instructions="Ask them",
            completion_label=f"Label {index + 1}",
            key=f"step-{index + 1}",
            order=index,
        )
    return exercise


def _mark_completed(session, completed_count):
    rows = list(session.session_steps.order_by("order"))
    for row in rows[:completed_count]:
        row.completed = True
        row.completion_result = f"done-{row.order}"
        row.save(update_fields=["completed", "completion_result", "updated_at"])
    return rows


def _run(consumer, exercise, *, completed_count=0, **fields):
    session = Session.objects.create(
        consumer=consumer,
        exercise=exercise,
        total_steps_no=exercise.steps_no,
        **fields,
    )
    SessionStep.create(session, exercise)
    _mark_completed(session, completed_count)
    return session


def _normalized(payload):
    """Same JSON the API renderer writes, then parsed back to plain data."""
    return json.loads(JSONRenderer().render(payload))


def _step_sql(queries):
    return [query["sql"] for query in queries if "sessionstep" in query["sql"].lower()]


class SessionListStepsQueryTests(TestCase):
    def setUp(self):
        self.consumer = Auth.create_consumer()
        self.token = Auth.get_access_token(self.consumer.user)
        self.other = Auth.create_consumer()
        self.exercise = _exercise()

    def _list_queries(self):
        with CaptureQueriesContext(connection) as captured:
            response = self._get("/sessions", access_token=self.token)
        self.assertEqual(response.status_code, 200, getattr(response, "json", None))
        queries = list(captured.captured_queries)
        return response, queries

    def test_list_payload_matches_the_unprefetched_path(self):
        """The list response stays identical to serializing each row with a fresh query."""
        now = timezone.now()
        check_in = _run(
            self.consumer,
            self.exercise,
            current_step_no=0,
            state=Constants.SESSION_STATE_CHECK_IN,
            pre_exercise_prompt_summary="Feeling tense",
        )
        active = _run(
            self.consumer,
            self.exercise,
            completed_count=1,
            current_step_no=2,
            state=Constants.SESSION_STATE_STEP_ACTIVE,
            pre_exercise_completed_at=now,
            pre_exercise_prompt_summary="Slept badly",
        )
        awaiting = _run(
            self.consumer,
            self.exercise,
            completed_count=1,
            current_step_no=2,
            state=Constants.SESSION_STATE_AWAITING_READY,
            resume_dismissed_at=now,
            pre_exercise_completed_at=now,
        )
        finished = _run(
            self.consumer,
            self.exercise,
            completed_count=4,
            current_step_no=4,
            completed=True,
            completed_at=now,
            state=Constants.SESSION_STATE_COMPLETED,
            pre_exercise_completed_at=now,
        )
        abandoned = _run(
            self.consumer,
            self.exercise,
            current_step_no=1,
            abandoned=True,
            state=Constants.SESSION_STATE_ABANDONED,
        )
        general = Session.objects.create(
            consumer=self.consumer,
            state=Constants.SESSION_STATE_GENERAL,
        )
        _consumer_sender, agent_sender = Participant.create_participants(active)
        active.last_message = Message.objects.create(
            session=active,
            sender=agent_sender,
            text="What happened just before the thought?",
        )
        active.save(update_fields=["last_message", "updated_at"])

        hidden = _run(
            self.consumer,
            self.exercise,
            current_step_no=1,
            authoring_test=True,
            state=Constants.SESSION_STATE_STEP_ACTIVE,
        )
        someone_else = _run(
            self.other,
            self.exercise,
            current_step_no=1,
            state=Constants.SESSION_STATE_STEP_ACTIVE,
        )

        owned = [check_in, active, awaiting, finished, abandoned, general]
        expected = {}
        for session in owned:
            bare = Session.objects.get(pk=session.pk)
            self.assertNotIn(
                "session_steps",
                getattr(bare, "_prefetched_objects_cache", {}),
            )
            expected[session.id] = _normalized(SessionListSerializer(bare).data)

        response, queries = self._list_queries()
        results = response.json["results"]
        returned_ids = {row["id"] for row in results}
        self.assertEqual(returned_ids, set(expected))
        self.assertNotIn(hidden.id, returned_ids)
        self.assertNotIn(someone_else.id, returned_ids)
        self.assertEqual(len(_step_sql(queries)), 1, _step_sql(queries))

        for row in results:
            snapshot = expected[row["id"]]
            self.assertEqual(row, snapshot)
            self.assertEqual(row["phase"], snapshot["phase"])
            self.assertEqual(row["pre_exercise"], snapshot["pre_exercise"])
            self.assertEqual(row["session_state"], snapshot["session_state"])
            self.assertEqual(row["resume_dismissed"], snapshot["resume_dismissed"])
            self.assertEqual(row["completed_steps"], snapshot["completed_steps"])
            self.assertEqual(row["total_steps"], snapshot["total_steps"])
            self.assertEqual(row["current_step_no"], snapshot["current_step_no"])

        by_id = {row["id"]: row for row in results}
        self.assertEqual(by_id[check_in.id]["phase"], "pre_exercise")
        self.assertEqual(by_id[check_in.id]["pre_exercise"]["pending"], True)
        self.assertEqual(by_id[check_in.id]["pre_exercise"]["summary"], "Feeling tense")
        self.assertEqual(by_id[check_in.id]["pre_exercise"]["start_button_label"], "Begin")
        self.assertEqual(by_id[check_in.id]["session_state"]["phase"], "check_in")
        self.assertEqual(by_id[check_in.id]["session_state"]["pending_action"], "start")
        self.assertEqual(by_id[check_in.id]["current_step_no"], 0)
        self.assertEqual(
            [step["status"] for step in by_id[check_in.id]["session_state"]["steps"]],
            ["pending", "pending", "pending", "pending"],
        )

        self.assertEqual(by_id[active.id]["phase"], "exercise")
        self.assertEqual(by_id[active.id]["completed_steps"], 1)
        self.assertEqual(by_id[active.id]["total_steps"], 4)
        self.assertEqual(by_id[active.id]["current_step_no"], 2)
        self.assertEqual(by_id[active.id]["session_state"]["phase"], "step_active")
        self.assertEqual(
            [step["status"] for step in by_id[active.id]["session_state"]["steps"]],
            ["completed", "active", "pending", "pending"],
        )
        self.assertEqual(
            [step["key"] for step in by_id[active.id]["session_state"]["steps"]],
            ["step-1", "step-2", "step-3", "step-4"],
        )
        self.assertEqual(by_id[active.id]["resume_dismissed"], False)
        self.assertEqual(
            by_id[active.id]["last_message"]["text"],
            "What happened just before the thought?",
        )
        self.assertIsNone(by_id[active.id]["last_message"]["exercise_session"])

        self.assertEqual(by_id[awaiting.id]["session_state"]["phase"], "awaiting_ready")
        self.assertEqual(by_id[awaiting.id]["session_state"]["pending_action"], "ready")
        self.assertEqual(by_id[awaiting.id]["resume_dismissed"], True)
        self.assertEqual(by_id[awaiting.id]["pre_exercise"]["pending"], False)
        self.assertEqual(by_id[awaiting.id]["pre_exercise"]["occurred"], True)

        self.assertEqual(by_id[finished.id]["phase"], "completed")
        self.assertEqual(by_id[finished.id]["completed_steps"], 4)
        self.assertEqual(by_id[finished.id]["current_step_no"], 5)
        self.assertEqual(by_id[finished.id]["session_state"]["phase"], "completed")
        self.assertEqual(by_id[finished.id]["session_state"]["pending_action"], "none")

        self.assertEqual(by_id[abandoned.id]["session_state"]["phase"], "abandoned")
        self.assertEqual(by_id[general.id]["phase"], "general")
        self.assertIsNone(by_id[general.id]["session_state"]["steps"])
        self.assertIsNone(by_id[general.id]["session_state"]["current_step_no"])
        self.assertEqual(by_id[general.id]["total_steps"], 0)

    def test_list_query_count_is_constant_for_two_and_ten_rows(self):
        _run(
            self.other,
            self.exercise,
            current_step_no=1,
            state=Constants.SESSION_STATE_STEP_ACTIVE,
        )
        for index in range(2):
            _run(
                self.consumer,
                self.exercise,
                completed_count=index % 4,
                current_step_no=(index % 4) + 1,
                state=Constants.SESSION_STATE_STEP_ACTIVE,
            )

        _, two_queries = self._list_queries()
        for index in range(8):
            _run(
                self.consumer,
                self.exercise,
                completed_count=(index + 2) % 4,
                current_step_no=((index + 2) % 4) + 1,
                state=Constants.SESSION_STATE_STEP_ACTIVE,
            )
        response, ten_queries = self._list_queries()
        self.assertEqual(len(response.json["results"]), 10)
        self.assertEqual(
            len(two_queries),
            len(ten_queries),
            "2 rows used %s queries (%s step queries); 10 rows used %s (%s step queries)"
            % (
                len(two_queries),
                len(_step_sql(two_queries)),
                len(ten_queries),
                len(_step_sql(ten_queries)),
            ),
        )
        self.assertEqual(len(_step_sql(two_queries)), 1, _step_sql(two_queries))
        self.assertEqual(len(_step_sql(ten_queries)), 1, _step_sql(ten_queries))

    def test_unprefetched_session_matches_prefetched_state(self):
        """Chat and other callers that did not prefetch still query, and match."""
        exercise = Exercise.objects.create(
            title="Out of order",
            subtitle="One thought",
            description="Work through one thought.",
            status=Constants.EXERCISE_STATUS_DRAFT,
            steps_no=3,
            icon="leaf",
            icon_background_color="tan",
        )
        steps = []
        for order in (2, 0, 1):
            steps.append(
                Step.objects.create(
                    exercise=exercise,
                    title=f"Step {order + 1}",
                    description="Describe it",
                    instructions="Ask them",
                    completion_label=f"Label {order + 1}",
                    key=f"k-{order}",
                    order=order,
                )
            )
        session = Session.objects.create(
            consumer=self.consumer,
            exercise=exercise,
            total_steps_no=3,
            current_step_no=2,
            state=Constants.SESSION_STATE_STEP_ACTIVE,
        )
        for step in steps:
            SessionStep.objects.create(
                session=session,
                step=step,
                order=step.order,
                completed=step.order == 0,
                completion_result="named it" if step.order == 0 else None,
            )

        bare = Session.objects.get(pk=session.pk)
        self.assertNotIn("session_steps", getattr(bare, "_prefetched_objects_cache", {}))
        with CaptureQueriesContext(connection) as captured:
            bare_state = build_session_state(bare)
            bare_progress = session_progress(bare)
        self.assertGreaterEqual(len(_step_sql(captured.captured_queries)), 1)

        loaded = SessionListSerializer.optimise(
            Session.objects.filter(pk=session.pk)
        ).get()
        unordered = Session.objects.prefetch_related(
            Prefetch(
                "session_steps",
                queryset=SessionStep.objects.select_related("step"),
            )
        ).get(pk=session.pk)
        nested = Session.objects.prefetch_related("session_steps__step").get(pk=session.pk)

        with CaptureQueriesContext(connection) as captured:
            loaded_state = build_session_state(loaded)
            loaded_progress = session_progress(loaded)
            unordered_state = build_session_state(unordered)
            nested_state = build_session_state(nested)
        self.assertEqual(captured.captured_queries, [])
        self.assertEqual(loaded_state, bare_state)
        self.assertEqual(unordered_state, bare_state)
        self.assertEqual(nested_state, bare_state)
        self.assertEqual(loaded_progress, bare_progress)
        self.assertEqual(
            [step["key"] for step in loaded_state["steps"]],
            ["k-0", "k-1", "k-2"],
        )
        self.assertEqual(
            [step["status"] for step in loaded_state["steps"]],
            ["completed", "active", "pending"],
        )

        cached_orders = [
            step.order for step in loaded._prefetched_objects_cache["session_steps"]
        ]
        build_session_state(loaded)
        self.assertEqual(
            cached_orders,
            [step.order for step in loaded._prefetched_objects_cache["session_steps"]],
        )
