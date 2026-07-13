from rest_framework import serializers

from .models import Session, SessionStep

from ..asset.serializers import AssetListSerializer

from ..consumer.serializers import ConsumerMinSerializer
from ..message.serializers import MessageDetailSerializer
from ..exercise.serializers import ExerciseDetailSerializer, ExerciseListSerializer
from ..utils.Serializers import ListModelSerializer


class SessionListSerializer(ListModelSerializer):

    consumer = ConsumerMinSerializer()
    last_message = MessageDetailSerializer()

    exercise = serializers.SerializerMethodField()
    
    class Meta:
        model = Session
        fields = '__all__'
    
    @classmethod
    def get_select_related_fields(cls):
        return [
            "exercise",
            "consumer__user",
            "last_message__sender__consumer__user",
            "last_message__sender__agent",
            "last_message__sender__agent__avatar",
            "last_message__asset__image",
        ]

    def get_exercise(self, session):

        exercise = session.exercise
        if not session.exercise:
            return None

        return ExerciseListSerializer(exercise).data


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
        fields = '__all__'

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
    def get_prefetch_related_fields(cls):
        return SessionListSerializer.get_prefetch_related_fields() + [
            "exercise__steps",
            "exercise__questions",
            "last_asset__file",
            "last_asset__image",
            "last_asset__post__file",
            "last_asset__post__tags",
            "last_asset__post__banner",
            "last_asset__post__thumbnail",
            "steps__last_asset__file",
            "steps__last_asset__image",
            "steps__last_asset__post__file",
            "steps__last_asset__post__tags",
            "steps__last_asset__post__banner",
            "steps__last_asset__post__thumbnail",
        ]


