from __future__ import unicode_literals

from .models import Summary
from .serializers import SummaryDetailSerializer
from ..utils.Permissions import (
    IsAdminPermission,
)
from ..utils.Views import SmartDetailAPIView


class Detail(SmartDetailAPIView):
    permission_classes = [IsAdminPermission]

    model = Summary
    detail_serializer = SummaryDetailSerializer

    def queryset(self, request, id):
        return Summary.objects.filter(consumer_id=id)
