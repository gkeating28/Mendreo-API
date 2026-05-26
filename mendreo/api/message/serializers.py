from rest_framework import serializers

from django.db.models import F

from ..exercise.models import Exercise

from ..agent.models import Agent
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
        message = super(MessageCreateSerializer, self).handle_create(validated_data=validated_data)

        agent_message = Agent.get_response(user_message=message, session=message.session)

        session = message.session

        if session.exercise_id:
            completion_result = agent_message.completion_result
            is_step_complete = agent_message.is_step_complete

            session_step = session.session_steps.filter(order=session.current_step_no - 1).first()
            if agent_message.asset:
                session.last_asset = agent_message.asset
                if session_step:
                    session_step.last_asset = agent_message.asset
                    session_step.save()

            if not is_step_complete:
                agent_message.completion_result = None
                agent_message.save(update_fields=["completion_result"])
            else:
                # put the agent message back to previous step so UI can show step completion
                agent_message.step_no = session.current_step_no
                agent_message.suggested_responses = []

                if session_step:
                    completion_label = session_step.step.completion_label

                    agent_message.completion_label = completion_label

                    session_step.completed = True
                    session_step.completion_result = completion_result
                    session_step.completion_label = completion_label
                    session_step.save()

                if session.current_step_no < session.total_steps_no:
                    session.current_step_no += 1
                else:
                    session.completed = True
                    Exercise.all_objects.filter(id=session.exercise_id).update(completions_no=F('completions_no') + 1)

                agent_message.save(update_fields=["step_no", "completion_label", "suggested_responses"])

            if agent_message.exercise:
                agent_message.exercise = None
                agent_message.save(update_fields=["exercise"])
                print(f"Remove exercise from {agent_message}")

        session.last_message = agent_message
        session.messages_no += 2
        session.agent_messages_no += 1
        session.consumer_messages_no += 1
        session.save()

        return agent_message


class MessageListSerializer(ListModelSerializer):
    
    sender = ParticipantListSerializer()
    asset = AssetDetailSerializer()
    exercise = ExerciseListSerializer()

    class Meta:
        model = Message
        fields = '__all__'
    
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
