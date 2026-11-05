from __future__ import unicode_literals

import json
from datetime import timedelta

from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime
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
from ..setting.models import Setting
from ..utils import Constants
from ..utils.Permissions import IsAdminPermission
from ..utils.Views import SmartAPIView, SmartDetailAPIView, SmartPaginationAPIView

ANSWERER_STALE_AFTER = timedelta(hours=24)
FAILURE_ERROR_LIMIT = 200


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


def _short_error(provider_id, errors, failed_ids) -> str:
    text = ""
    prefix = f"{provider_id}/"
    if isinstance(errors, list):
        for item in errors:
            if isinstance(item, str) and item.startswith(prefix):
                text = item
                break
        if not text and provider_id in failed_ids:
            index = list(failed_ids).index(provider_id)
            if index < len(errors) and isinstance(errors[index], str):
                text = errors[index]
    return text[:FAILURE_ERROR_LIMIT]


def _empty_provider_stats(provider_id, name="", provider_type=""):
    return {
        "id": provider_id,
        "name": name or "",
        "provider": provider_type or "",
        "failover_count": 0,
        "failure_count": 0,
        "last_failure_at": None,
        "last_error": "",
    }


def _read_active_answerer():
    row = Setting.objects.filter(key=Constants.SETTING_KEY_AI_LAST_ANSWERER).first()
    if row is None or not row.value:
        return None
    try:
        data = json.loads(row.value)
    except (TypeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    provider_id = str(data.get("provider_id") or "")
    if not provider_id:
        return None
    at = parse_datetime(str(data.get("at") or ""))
    if at is None:
        return None
    if timezone.is_naive(at):
        at = timezone.make_aware(at, timezone.get_current_timezone())
    if timezone.now() - at >= ANSWERER_STALE_AFTER:
        return None
    return {
        "id": provider_id,
        "name": str(data.get("provider_name") or ""),
        "at": at.isoformat(),
    }


def _failover_stats():
    since = timezone.now() - ANSWERER_STALE_AFTER
    configured = list(AiProvider.objects.all().order_by("-is_default", "name"))
    stats = {
        provider.id: _empty_provider_stats(provider.id, provider.name, provider.provider)
        for provider in configured
    }
    logs = AiProviderAuditLog.objects.filter(
        action=Constants.AI_PROVIDER_AUDIT_FAILOVER,
        created_at__gte=since,
    ).order_by("created_at")
    for log in logs:
        winner = str(log.provider_id_snapshot or "")
        if winner:
            row = stats.get(winner)
            if row is None:
                row = _empty_provider_stats(
                    winner,
                    log.provider_name_snapshot,
                    log.provider_type_snapshot,
                )
                stats[winner] = row
            row["failover_count"] += 1
        detail = log.detail if isinstance(log.detail, dict) else {}
        failed = detail.get("failed_providers") or []
        errors = detail.get("errors") or []
        if not isinstance(failed, list):
            continue
        failed_ids = [str(item) for item in failed]
        for provider_id in failed_ids:
            row = stats.get(provider_id)
            if row is None:
                row = _empty_provider_stats(provider_id)
                stats[provider_id] = row
            row["failure_count"] += 1
            row["last_failure_at"] = log.created_at.isoformat()
            error = _short_error(provider_id, errors, failed_ids)
            if error:
                row["last_error"] = error
    ordered = [provider.id for provider in configured]
    ordered.extend(provider_id for provider_id in stats if provider_id not in ordered)
    return [stats[provider_id] for provider_id in ordered]


class ProviderStatus(SmartAPIView):
    permission_classes = [IsAdminPermission]

    def get(self, request):
        default = AiProvider.objects.filter(is_default=True).order_by("-updated_at").first()
        default_payload = None
        if default is not None:
            default_payload = {
                "id": default.id,
                "name": default.name,
                "provider": default.provider,
                "default_model": default.default_model,
            }
        active = _read_active_answerer()
        degraded = bool(active) and (
            default_payload is None or active["id"] != default_payload["id"]
        )
        return Response(
            {
                "default": default_payload,
                "active": active,
                "degraded": degraded,
                "providers": _failover_stats(),
            },
            status=status.HTTP_200_OK,
        )
