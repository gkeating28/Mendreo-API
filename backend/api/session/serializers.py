from rest_framework import serializers

from .models import Session, SessionStep

from ..asset.serializers import AssetListSerializer

from ..consumer.serializers import ConsumerMinSerializer
from ..exercise.serializers import ExerciseDetailSerializer, ExerciseListSerializer
from ..utils.Serializers import ListModelSerializer


class SessionLastMessageSerializer(ListModelSerializer):
    """Slim last-message payload for session list/detail (avoids nested asset/exercise)."""

    sender = serializers.SerializerMethodField()

    class Meta:
        from ..message.models import Message
        model = Message
        fields = [
            "id",
            "text",
            "created_at",
            "sender",
            "suggested_responses",
            "is_step_complete",
            "step_no",
            "completion_label",
            "asset",
            "exercise",
        ]

    def get_sender(self, message):
        from ..participant.serializers import ParticipantListSerializer
        return ParticipantListSerializer(message.sender).data


class SessionListSerializer(ListModelSerializer):

    consumer = ConsumerMinSerializer()
    last_message = SessionLastMessageSerializer()

    exercise = serializers.SerializerMethodField()
    phase = serializers.SerializerMethodField()
    pre_exercise = serializers.SerializerMethodField()
    
    class Meta:
        model = Session
        # Internal AI state — large blobs (100s of KB) that must never go to clients.
        exclude = ["cached_prompt", "cached_history"]
    
    @classmethod
    def get_select_related_fields(cls):
        return [
            "exercise",
            "consumer__user",
            "last_message__sender__consumer__user",
            "last_message__sender__agent",
            "last_message__sender__agent__avatar",
        ]

    @classmethod
    def get_prefetch_related_fields(cls):
        # List uses ExerciseListSerializer (no steps/questions) — do not prefetch them.
        return []

    def get_exercise(self, session):

        exercise = session.exercise
        if not session.exercise:
            return None

        return ExerciseListSerializer(exercise).data

    def get_phase(self, session):
        if session.in_pre_exercise_phase():
            return "pre_exercise"
        if session.completed:
            return "completed"
        if session.exercise_id:
            return "exercise"
        return "general"

    def get_pre_exercise(self, session):
        exercise = session.exercise
        pending = session.in_pre_exercise_phase()
        occurred = session.had_pre_exercise_checkin()
        label = None
        if exercise and (pending or occurred):
            label = exercise.pre_exercise_start_button_label or "Start exercise"
        return {
            "pending": pending,
            "occurred": occurred,
            "summary": session.pre_exercise_prompt_summary,
            "completed_at": session.pre_exercise_completed_at,
            "start_button_label": label,
        }


class SessionStepListSerializer(ListModelSerializer):

    last_asset = AssetListSerializer()

    class Meta:
        model = SessionStep
        fields = [
            "step",
            "last_asset",
            "completed",
            "completion_label",
            "completion_result",
        ]


class SessionDetailSerializer(SessionListSerializer):

    last_asset = AssetListSerializer()

    steps = SessionStepListSerializer(source="session_steps", many=True, order_by="order")

    class Meta(SessionListSerializer.Meta):
        pass

    def get_exercise(self, session):
        from ..question.serializers import Question, QuestionExerciseDetailSerializer

        exercise = session.exercise
        if not session.exercise:
            return None

        data = ExerciseDetailSerializer(exercise).data

        data["questions"] = Question.get_with_attributes(
            queryset=session.questions,
            consumer=session.consumer,
            serializer=QuestionExerciseDetailSerializer,
        )

        return data

    @classmethod
    def get_select_related_fields(cls):
        return SessionListSerializer.get_select_related_fields() + [
            "last_asset__file",
            "last_asset__image",
            "last_asset__post__file",
            "last_asset__post__banner",
            "last_asset__post__thumbnail",
        ]

    @classmethod
    def get_prefetch_related_fields(cls):
        return [
            "exercise__steps",
            "exercise__questions",
            "last_asset__post__tags",
            "session_steps__step",
            "session_steps__last_asset__file",
            "session_steps__last_asset__image",
            "session_steps__last_asset__post__file",
            "session_steps__last_asset__post__tags",
            "session_steps__last_asset__post__banner",
            "session_steps__last_asset__post__thumbnail",
            "questions",
        ]
