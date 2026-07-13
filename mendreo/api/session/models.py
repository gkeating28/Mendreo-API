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

    current_step_no = models.PositiveIntegerField(null=True)

    cached_prompt = models.TextField(null=True)

    cached_history = models.JSONField(null=True)

    usage = models.JSONField(null=True)

    def __str__(self):
        """Return a human-readable representation of the model instance."""
        return "Session: {}".format(self.id)

    def get_permission_key(self):
        """Return the permission key for role-based access control"""
        return "sessions"

    @staticmethod
    def get_or_create(consumer, exercise: Exercise = None):
        from ..agent.models import Agent
        from ..participant.models import Participant
        today_date = DateUtils.today()

        session = Session.objects.filter(
            consumer=consumer,
            exercise=exercise,
            created_at__date=today_date
        ).order_by("-created_at").first()

        if session and not session.completed:
            return session

        completed = None
        total_steps_no = None
        current_step_no = None

        if exercise:
            completed = False
            current_step_no = 1
            total_steps_no = exercise.steps_no

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
            message = Message(
                session=session,
                sender=consumer_participant,
                text="Hi, I'd like to practise this exercise. Can you greet me and explain the exercise please?"
            )
            agent_message = Agent.get_response(user_message=message, session=session)
            session.last_message = agent_message
            session.messages_no += 1
            session.agent_messages_no += 1
            session.save()

        return session

    @staticmethod
    def get_with_messages(date, consumer, exercise):

        sessions = consumer.sessions.filter(created_at__date=date)

        if exercise:
            sessions = sessions.filter(exercise=exercise)

        session_ids = sessions.values_list("id", flat=True)

        if not session_ids:
            return []

        messages = Message.objects.filter(session_id__in=session_ids).select_related('sender').order_by('created_at')

        sessions_data = []

        for session_id in session_ids:
            session_messages = []

            for message in messages:
                if message.session_id == session_id:
                    session_messages.append(message)

            sessions_data.append({
                "session": session_id,
                "messages": session_messages
            })

        return sessions_data

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

