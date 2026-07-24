from ..utils.Serializers import (
    ListModelSerializer,
)

from ..price.serializers import PriceListSerializer

from .models import Package


class PackageListSerializer(ListModelSerializer):
    price = PriceListSerializer()

    class Meta:
        model = Package
        fields = "__all__"

    @classmethod
    def get_select_related_fields(cls):
        return ["price"]


class PackageDetailSerializer(PackageListSerializer):
    pass
