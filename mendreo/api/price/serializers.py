from .models import Price

from ..utils.Serializers import ListModelSerializer

from ..currency.serializers import CurrencyListSerializer


class PriceListSerializer(ListModelSerializer):
    currency = CurrencyListSerializer()

    class Meta:
        model = Price
        fields = "__all__"

    def validate_amount(self, amount):
        if amount < 100:
            raise self.raise_validation_error("amount", "must be greater than or equal to 100")

        return amount

    @classmethod
    def get_select_related_fields(cls):
        return ["currency"]


class PriceDetailSerializer(PriceListSerializer):
    pass
