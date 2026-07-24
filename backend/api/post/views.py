from __future__ import unicode_literals

from datetime import datetime

from .models import Post
from ..event.models import Event

from .serializers import (
    PostCreateSerializer,
    PostEditSerializer,
    PostListSerializer,
    PostDetailSerializer,
    PostAdminListSerializer,
    PostAdminDetailSerializer,
)

from ..utils.Permissions import (
    IsAdminPermission,
    IsConsumerPermission
)

from ..utils import QueryParams, Constants

from ..utils.Views import SmartPaginationAPIView, SmartDetailAPIView


class ListCreate(SmartPaginationAPIView):

    model = Post
    list_serializer = PostListSerializer
    detail_serializer = PostDetailSerializer
    create_serializer = PostCreateSerializer

    admin_list_serializer = PostAdminListSerializer
    admin_detail_serializer = PostAdminDetailSerializer

    permission_classes = [IsAdminPermission | IsConsumerPermission]

    def add_filters(self, query, request):
        status = QueryParams.get_str(request, "status")
        search_term = QueryParams.get_str(request, "search_term")
        type_ = QueryParams.get_enum(request, "type", options=Constants.POST_TYPES)

        if self.is_consumer_request():
            status = Constants.POST_STATUS_PUBLISHED
            query = query.filter(published_at__date__lte=datetime.now().strftime("%Y-%m-%d"))

        if status:
            query = query.filter(status=status)

        if type_:
            query = query.filter(type=type_)

        if search_term:
            query = query.filter(title__icontains=search_term)

        return query

    def override_post_data(self, request, data):
        self.inject_user(request, "created_by")
        return data

    def has_permission(self, request, method):
        if method == "GET":
            return True

        return self.is_admin_request()

    def get_paginated_response(self, data):
        if self.is_consumer_request():
            consumer = self.get_consumer_from_request()
            Event.create_impressions(consumer=consumer, posts_data=data)

        return super(ListCreate, self).get_paginated_response(data)


class Detail(SmartDetailAPIView):
    permission_classes = [IsAdminPermission | IsConsumerPermission]

    model = Post
    edit_serializer = PostEditSerializer
    detail_serializer = PostDetailSerializer

    admin_detail_serializer = PostAdminDetailSerializer

    deletable = True

    def has_permission(self, request, method):
        if method == "GET":
            return True

        return self.is_admin_request()

    def override_response_data(self, request, data, instance):
        if self.is_consumer_request():
            consumer = self.get_consumer_from_request()
            Event.create_view(consumer=consumer, post=instance)

        return super(Detail, self).override_response_data(request, data, instance)
