from .models import Currency
from ..utils.Serializers import ListModelSerializer


class CurrencyListSerializer(ListModelSerializer):

    class Meta:
        model = Currency
        fields = "__all__"


class CurrencyDetailSerializer(CurrencyListSerializer):
    pass
