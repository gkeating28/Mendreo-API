from __future__ import unicode_literals

from django.db import transaction
from rest_framework import status
from rest_framework.response import Response

from .models import AiProvider, AiProviderAuditLog
from .serializers import (
    AiProviderCreateSerializer,
    AiProviderEditSerializer,
    AiProviderDetailSerializer,
    AiProviderListSerializer,
    AiProviderAuditLogSerializer,
)
from ..utils import Constants
from ..utils.Permissions import IsAdminPermission
from ..utils.Views import SmartAPIView, SmartDetailAPIView, SmartPaginationAPIView


class ListCreate(SmartPaginationAPIView):
    model = AiProvider
    list_serializer = AiProviderListSerializer
    detail_serializer = AiProviderDetailSerializer
    create_serializer = AiProviderCreateSerializer
    permission_classes = [IsAdminPermission]

    @transaction.atomic
    def post(self, request):
        if not self.has_permission(request, "POST"):
            return self.get_permission_denied_response(request, "POST")

        serializer = self.create_serializer(
            data=request.data,
            context={"actor": request.user, "request": request},
        )
        serializer.is_valid(raise_exception=True)
        instance = serializer.save()
        return Response(
            self.detail_serializer(instance).data,
            status=status.HTTP_201_CREATED,
        )


class Detail(SmartDetailAPIView):
    model = AiProvider
    edit_serializer = AiProviderEditSerializer
    detail_serializer = AiProviderDetailSerializer
    permission_classes = [IsAdminPermission]
    deletable = True

    @transaction.atomic
    def patch(self, request, id):
        if not self.has_permission(request, "PATCH"):
            return self.get_permission_denied_response(request, "PATCH")

        instance = self.queryset(request, id).first()
        if not instance:
            return self.get_instance_not_found_response(request, "PATCH")

        serializer = self.edit_serializer(
            instance,
            data=request.data,
            partial=self.partial,
            context={"actor": request.user, "request": request},
        )
        serializer.is_valid(raise_exception=True)
        instance = serializer.save()
        return Response(self.detail_serializer(instance).data, status=status.HTTP_200_OK)

    def handle_delete(self, instance):
        instance._audit_actor = self.request.user
        return instance.delete()


class SetDefault(SmartAPIView):
    permission_classes = [IsAdminPermission]

    def post(self, request, id):
        try:
            provider = AiProvider.objects.get(id=id)
        except AiProvider.DoesNotExist:
            return self.not_found()

        if not provider.enabled:
            return self.respond_with(
                "Cannot set a disabled provider as default",
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        AiProvider.clear_default_flags(except_id=provider.id)
        provider.is_default = True
        provider.save(update_fields=["is_default", "updated_at"])

        AiProviderAuditLog.log(
            provider=provider,
            action=Constants.AI_PROVIDER_AUDIT_SET_DEFAULT,
            actor=request.user,
            detail={"via": "set-default"},
        )

        return Response(AiProviderDetailSerializer(provider).data, status=status.HTTP_200_OK)


class AuditList(SmartPaginationAPIView):
    model = AiProviderAuditLog
    list_serializer = AiProviderAuditLogSerializer
    detail_serializer = AiProviderAuditLogSerializer
    permission_classes = [IsAdminPermission]

    def has_permission(self, request, method):
        return method == "GET" and self.is_admin_request()

    def add_filters(self, query, request):
        provider_id = request.query_params.get("provider")
        if provider_id:
            query = query.filter(provider_id_snapshot=provider_id)
        action = request.query_params.get("action")
        if action:
            query = query.filter(action=action)
        return query
