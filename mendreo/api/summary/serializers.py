from .models import Summary
from ..utils.Serializers import ListModelSerializer


class SummaryListSerializer(ListModelSerializer):

    class Meta:
        model = Summary
        fields = '__all__'


class SummaryDetailSerializer(SummaryListSerializer):
    pass
