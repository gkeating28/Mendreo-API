from rest_framework import serializers

from ..asset.serializers import AssetDetailSerializer

from ..exercise.serializers import ExerciseListSerializer

from ..consumer.models import Consumer
from ..message.models import Message
from ..participant.models import Participant
from ..participant.serializers import ParticipantListSerializer

from ..utils.Serializers import CreateModelSerializer, ListModelSerializer


class MessageCreateSerializer(CreateModelSerializer):
    
    consumer = serializers.PrimaryKeyRelatedField(queryset=Consumer.objects.all())
    
    class Meta:
        model = Message
        fields = [
            "text",
            "session",
            "consumer"
        ]
    
    def validate(self, attrs):
        session = attrs.get('session')
        consumer = attrs.pop('consumer')
            
        participant = Participant.objects.filter(session=session, consumer=consumer).first()

        if not participant:
            self.raise_validation_error(
                key="consumer",
                error="You are not a participant in this session."
            )

        attrs['sender'] = participant
            
        if session.completed:
            self.raise_validation_error(
                key="session",
                error="Not allowed to send messages for past sessions."
            )
            
        return attrs

    def handle_create(self, validated_data):
        # AI response is triggered from the view AFTER the surrounding
        # transaction commits. Calling the Railway worker here (inside
        # @transaction.atomic) means the worker's DB connection cannot see
        # this row yet → get_object_or_404 → 404 → client JSON parse errors.
        return super(MessageCreateSerializer, self).handle_create(validated_data=validated_data)


class MessageListSerializer(ListModelSerializer):
    
    sender = ParticipantListSerializer()
    asset = AssetDetailSerializer()
    exercise = ExerciseListSerializer()

    class Meta:
        model = Message
        fields = [
            "id",
            "session",
            "sender",
            "text",
            "reasoning",
            "suggested_responses",
            "step_no",
            "completion_label",
            "completion_result",
            "is_step_complete",
            "asset",
            "exercise",
            "usage",
            "created_at",
            "updated_at",
        ]
    
    @classmethod
    def get_select_related_fields(cls):
        return [
            "exercise",
            "sender__agent__avatar",
            "sender__consumer__user",
            "asset__file",
            "asset__image",
            "asset__post__file",
            "asset__post__banner",
            "asset__post__thumbnail",
        ]

class MessageDetailSerializer(MessageListSerializer):
    pass
