from __future__ import unicode_literals

from django.db.models import Max
from rest_framework import status
from rest_framework.response import Response

from .models import PromptVersion
from ..utils import Constants
from ..utils.Permissions import IsAdminPermission
from ..utils.Views import SmartAPIView


class PromptVersions(SmartAPIView):
    permission_classes = [IsAdminPermission]
    model = PromptVersion

    def get(self, request, key):
        if key not in Constants.PROMPT_KEYS:
            return self.not_found()
        rows = PromptVersion.objects.filter(key=key).order_by("-version")
        return Response({"key": key, "versions": [_row(row) for row in rows]})

    def post(self, request, key):
        if key not in Constants.PROMPT_KEYS:
            return self.not_found()
        body = (request.data.get("body") if isinstance(request.data, dict) else None) or ""
        if not str(body).strip():
            return self.respond_with(
                "A version needs a body.",
                key="body",
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        latest = PromptVersion.objects.filter(key=key).aggregate(Max("version"))["version__max"] or 0
        row = PromptVersion.objects.create(
            key=key,
            body=str(body),
            version=latest + 1,
            active=False,
            created_by=request.user if request.user.is_authenticated else None,
        )
        return Response(_row(row), status=status.HTTP_201_CREATED)


class PromptActivate(SmartAPIView):
    permission_classes = [IsAdminPermission]
    model = PromptVersion

    def post(self, request, key, version):
        if key not in Constants.PROMPT_KEYS:
            return self.not_found()
        row = PromptVersion.objects.filter(key=key, version=version).first()
        if row is None:
            return self.not_found()
        PromptVersion.objects.filter(key=key, active=True).update(active=False)
        row.active = True
        row.save(update_fields=["active", "updated_at"])
        return Response(_row(row))


def _row(row: PromptVersion) -> dict:
    author = None
    if row.created_by_id:
        author = row.created_by_id
    return {
        "id": row.id,
        "key": row.key,
        "version": row.version,
        "active": row.active,
        "body": row.body,
        "created_by": author,
        "created_at": row.created_at,
    }
