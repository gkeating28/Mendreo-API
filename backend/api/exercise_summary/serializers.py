from .models import ExerciseSummary
from ..utils.Serializers import ListModelSerializer


class ExerciseSummaryListSerializer(ListModelSerializer):

    class Meta:
        model = ExerciseSummary
        fields = '__all__'


class ExerciseSummaryDetailSerializer(ExerciseSummaryListSerializer):
    pass
