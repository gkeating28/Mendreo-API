from .models import Participant
from ..agent.serializers import AgentMinSerializer
from ..consumer.serializers import ConsumerMinSerializer
from ..utils.Serializers import ListModelSerializer

class ParticipantListSerializer(ListModelSerializer):
    consumer = ConsumerMinSerializer()
    agent = AgentMinSerializer()
    
    class Meta:
        model = Participant
        fields = ['consumer', 'agent']
    
    @classmethod
    def get_select_related_fields(cls):
        return ["agent__avatar", "consumer__user"]
    
class ParticipantDetailSerializer(ParticipantListSerializer):
    pass