from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import models

from ..asset.models import Asset
from ..step.models import Step
from ..consumer.models import Consumer
from ..message.models import Message
from ..exercise.models import Exercise

from ..utils import Constants, DateUtils
from ..utils.Fields import CharIDField, EnumField
from ..utils.Models import SmartModel


class Session(SmartModel):
    id = CharIDField(primary_key=True, prefix="ssn_")
    
    consumer = models.ForeignKey(Consumer, related_name='sessions', on_delete=models.CASCADE)
    last_asset = models.ForeignKey(Asset, related_name='sessions_as_last_asset', null=True, on_delete=models.SET_NULL)
    last_message = models.ForeignKey(Message, related_name='sessions_as_last_message', null=True, on_delete=models.SET_NULL)
    exercise = models.ForeignKey(Exercise, related_name='sessions', null=True, on_delete=models.SET_NULL)

    messages_no = models.PositiveIntegerField(default=0)
    consumer_messages_no = models.PositiveIntegerField(default=0)
    agent_messages_no = models.PositiveIntegerField(default=0)

    subject = models.CharField(max_length=255, null=True)

    rating = models.DecimalField(max_digits=3, decimal_places=2, null=True, validators=[MinValueValidator(0), MaxValueValidator(10)])

    rating_reason = models.TextField(null=True)

    risk_level = EnumField(options=Constants.RISK_LEVEL_CHOICES, null=True)

    total_steps_no = models.PositiveIntegerField(null=True)

    completed = models.BooleanField(null=True, default=False)

    # Paused exercise run the user left to start a different attempt.
    # Keep the row and its answers; do not surface it as in_progress.
    abandoned = models.BooleanField(default=False)

    current_step_no = models.PositiveIntegerField(null=True)

    cached_prompt = models.TextField(null=True)

    cached_history = models.JSONField(null=True)

    usage = models.JSONField(null=True)

    # Pre-Exercise Prompt check-in (V2). During check-in, current_step_no is 0.
    pre_exercise_prompt_summary = models.TextField(null=True, blank=True)
    pre_exercise_completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(
                fields=["consumer", "created_at"],
                name="session_consumer_created_idx",
            ),
            models.Index(
                fields=["consumer", "exercise", "created_at"],
                name="session_cons_ex_created_idx",
            ),
        ]

    def __str__(self):
        """Return a human-readable representation of the model instance."""
        return "Session: {}".format(self.id)

    def get_permission_key(self):
        """Return the permission key for role-based access control"""
        return "sessions"

    def in_pre_exercise_phase(self) -> bool:
        """True while the session is in the pre-exercise check-in (before Step 1)."""
        return bool(self.exercise_id) and self.current_step_no == 0

    def had_pre_exercise_checkin(self) -> bool:
        """True if a pre-exercise check-in completed for this session."""
        return self.pre_exercise_completed_at is not None

    @staticmethod
    def get_or_create(consumer, exercise: Exercise = None, force_new: bool = False):
        from ..participant.models import Participant
        from ..exercise.pre_exercise import should_run_pre_exercise_checkin

        if exercise:
            paused = Session.objects.filter(
                consumer=consumer,
                exercise=exercise,
                completed=False,
                abandoned=False,
            )
            if force_new:
                paused.update(abandoned=True)
            else:
                existing = paused.order_by("-updated_at", "-created_at").first()
                if existing:
                    return existing
        else:
            start, end = DateUtils.day_bounds()
            session = Session.objects.filter(
                consumer=consumer,
                exercise=None,
                created_at__gte=start,
                created_at__lt=end,
            ).order_by("-created_at").first()

            if session and not session.completed:
                return session

        completed = None
        total_steps_no = None
        current_step_no = None
        run_pre_exercise = False

        if exercise:
            completed = False
            total_steps_no = exercise.steps_no
            run_pre_exercise = should_run_pre_exercise_checkin(consumer, exercise)
            # Cadence: every repeat (incl. same-day second runs after a completed session).
            # Resume of an incomplete paused run is handled above via get_or_create.
            current_step_no = 0 if run_pre_exercise else 1

        session = Session.objects.create(
            consumer=consumer,
            risk_level=None,
            exercise=exercise,
            completed=completed,
            total_steps_no=total_steps_no,
            current_step_no=current_step_no
        )

        if exercise:
            SessionStep.create(session, exercise)

            from ..question.models import Question
            from cuid import cuid

            questions = list(exercise.questions.all())
            for question in questions:
                question.id = cuid()
                question.exercise = None
                question.session = session
            Question.objects.bulk_create(questions)

        consumer_participant, _ = Participant.create_participants(session=session)

        if exercise:
            from ..utils.AIWorkerClient import request_session_greeting
            request_session_greeting(session)

        return session

    @staticmethod
    def create_general(consumer):
        """Always create a fresh general chat. Does not reuse today's session."""
        from ..participant.models import Participant

        session = Session.objects.create(
            consumer=consumer,
            risk_level=None,
            exercise=None,
            completed=None,
        )
        Participant.create_participants(session=session)
        return session

    @staticmethod
    def get_with_messages(date, consumer, exercise):
        start, end = DateUtils.day_bounds(date)

        sessions = consumer.sessions.filter(created_at__gte=start, created_at__lt=end)

        if exercise:
            sessions = sessions.filter(exercise=exercise)

        session_ids = list(sessions.values_list("id", flat=True))

        if not session_ids:
            return []

        messages = (
            Message.objects
            .filter(session_id__in=session_ids)
            .select_related('sender')
            .order_by('created_at')
        )

        messages_by_session = {session_id: [] for session_id in session_ids}
        for message in messages:
            messages_by_session[message.session_id].append(message)

        return [
            {"session": session_id, "messages": messages_by_session[session_id]}
            for session_id in session_ids
        ]

    def get_chat_history(self):
        from pydantic_ai.messages import ModelMessagesTypeAdapter

        if not self.cached_history:
            return []

        return ModelMessagesTypeAdapter.validate_python(self.cached_history)

    def update_chat_history(self, result):
        from pydantic_core import to_jsonable_python

        history = result.all_messages()
        self.cached_history = to_jsonable_python(history)
        self.save(update_fields=["cached_history"])
        return self


class SessionStep(SmartModel):
    id = CharIDField(primary_key=True, prefix="ssnstp_")

    step = models.ForeignKey(Step, related_name='session_steps', on_delete=models.CASCADE)
    session = models.ForeignKey(Session, related_name='session_steps', on_delete=models.CASCADE)
    last_asset = models.ForeignKey(Asset, related_name='session_last_asset', null=True, on_delete=models.CASCADE)

    completed = models.BooleanField(default=False)

    completion_label = models.TextField(null=True)
    completion_result = models.TextField(null=True)

    order = models.PositiveIntegerField()

    @staticmethod
    def create(session, exercise):
        if not exercise:
            exercise = session.exercise

        if not exercise:
            return []

        session_steps = []
        for step in exercise.steps.order_by("order"):
            session_steps.append(
                SessionStep(
                    step=step,
                    session=session,
                    order=step.order,
                    completed=False,
                )
            )
        SessionStep.objects.bulk_create(session_steps)
