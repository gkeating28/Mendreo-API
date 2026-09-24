from rest_framework import serializers

from .models import Session, SessionStep

from ..asset.serializers import AssetListSerializer

from ..consumer.serializers import ConsumerMinSerializer
from ..exercise.serializers import ExerciseDetailSerializer, ExerciseListSerializer
from ..utils import Constants
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
            "suggested_responses_kind",
            "question_kind",
            "resources",
            "completion_label",
            "asset",
            "exercise",
            "exercise_session",
        ]

    def get_sender(self, message):
        from ..participant.serializers import ParticipantListSerializer
        return ParticipantListSerializer(message.sender).data

    exercise_session = serializers.SerializerMethodField()

    def get_exercise_session(self, message):
        from ..utils.ExerciseOffer import exercise_session_payload_for_message

        return exercise_session_payload_for_message(self, message)


class SessionListSerializer(ListModelSerializer):

    consumer = ConsumerMinSerializer()
    last_message = SessionLastMessageSerializer()

    exercise = serializers.SerializerMethodField()
    phase = serializers.SerializerMethodField()
    pre_exercise = serializers.SerializerMethodField()
    session_state = serializers.SerializerMethodField()
    
    class Meta:
        model = Session
        # Internal AI state — large blobs (100s of KB) that must never go to clients.
        # WP1 columns stay off the wire until session_state is introduced.
        exclude = [
            "cached_prompt",
            "cached_prompt_meta",
            "state",
            "closed_at",
            "form_answers",
            "prompt_version",
            "live_risk_level",
            "history_summary",
        ]
    
    @classmethod
    def get_select_related_fields(cls):
        return [
            "exercise",
            "consumer__user",
            "last_message__sender__consumer__user",
            "last_message__sender__agent",
            "last_message__sender__agent__avatar",
            "last_message__session",
            "last_message__exercise",
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

    def get_session_state(self, session):
        from django.conf import settings

        if not getattr(settings, "AI_STATE_MACHINE_ENABLED", True):
            return None
        from ..utils.SessionStateMachine import build_session_state

        return build_session_state(session)

    def to_representation(self, instance):
        from django.conf import settings

        data = super().to_representation(instance)
        if not getattr(settings, "AI_STATE_MACHINE_ENABLED", True):
            data.pop("session_state", None)
        request = self.context.get("request")
        user = getattr(request, "user", None)
        if user is not None and getattr(user, "type", None) == Constants.USER_TYPE_ADMIN:
            data["live_risk_level"] = instance.live_risk_level
            data["state_transitions"] = _state_transitions(instance)
        return data


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
            "result_confidence",
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


def _state_transitions(session) -> list:
    events = []
    if session.pre_exercise_completed_at:
        events.append(
            {
                "kind": "check_in_completed",
                "at": session.pre_exercise_completed_at,
            }
        )
    for session_step in session.session_steps.all():
        if not session_step.completed:
            continue
        events.append(
            {
                "kind": "step_completed",
                "step_no": session_step.order + 1,
                "result": session_step.completion_result,
                "confidence": session_step.result_confidence,
                "at": session_step.updated_at,
            }
        )
    from ..message.models import Message

    kinds = (
        Constants.SUGGESTED_RESPONSES_KIND_READY,
        Constants.SUGGESTED_RESPONSES_KIND_FINISH,
    )
    for message in Message.objects.filter(session=session, suggested_responses_kind__in=kinds):
        events.append(
            {
                "kind": message.suggested_responses_kind,
                "at": message.created_at,
                "message_id": message.id,
            }
        )
    if session.closed_at:
        events.append({"kind": "closed", "at": session.closed_at})
    events.sort(key=lambda item: item["at"] or session.created_at)
    return events
