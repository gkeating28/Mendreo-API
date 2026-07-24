from __future__ import unicode_literals

from .models import Message
from .serializers import MessageDetailSerializer, MessageCreateSerializer, MessageListSerializer
from ..utils import QueryParams
from ..utils.Permissions import (
    IsConsumerPermission, IsAdminPermission,
)
from ..utils.Views import SmartPaginationAPIView


class ListCreate(SmartPaginationAPIView):
    permission_classes = [IsAdminPermission | IsConsumerPermission]

    model = Message
    detail_serializer = MessageDetailSerializer
    create_serializer = MessageCreateSerializer
    list_serializer = MessageListSerializer
    
    def add_filters(self, queryset, request):
        session_id = QueryParams.get_str(request, "session_id")
        consumer_id = QueryParams.get_str(request, "consumer_id")
        
        if self.is_consumer_request():
            consumer_id = self.get_consumer_from_request().user.id
        
        if session_id:
            queryset = queryset.filter(session_id=session_id)
            
        if consumer_id:
            queryset = queryset.filter(session__consumer_id=consumer_id)
            
        return queryset
    
    def override_post_data(self, request, data):

        data['consumer'] = self.get_consumer_from_request().user_id

        return data
