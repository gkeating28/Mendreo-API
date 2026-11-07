from rest_framework import status
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from ..utils.Permissions import IsAdminPermission
from ..utils.Views import SmartAPIView
from .models import InviteCode
from .serializers import InviteCodeAdminSerializer, InviteCodeBatchCreateSerializer
from .services import RedeemRejected, create_codes, redeem, reset_code


class Redeem(SmartAPIView):
    """Unauthenticated. First use creates the account; later uses log into it."""

    permission_classes = []
    consent_exempt = True
    authentication_classes = []

    def post(self, request):
        raw = request.data.get("code") if hasattr(request.data, "get") else None
        try:
            payload = redeem(raw, request)
        except RedeemRejected as rejected:
            return self.respond_with(rejected.detail, status_code=rejected.status_code)
        return Response(payload, status=status.HTTP_200_OK)


class InviteAdminView(SmartAPIView):
    permission_classes = [IsAdminPermission]
    role_permission = True

    def _denied(self, request, method):
        if not self.has_role_permission(method, InviteCode):
            return self.get_permission_denied_response(request, method)
        return None


class InviteCodeListCreate(InviteAdminView):

    def get(self, request):
        denied = self._denied(request, "GET")
        if denied:
            return denied

        codes = (
            InviteCode.objects.select_related("consumer__user")
            .order_by("-created_at")
        )
        return Response(
            InviteCodeAdminSerializer(codes, many=True).data,
            status=status.HTTP_200_OK,
        )

    def post(self, request):
        denied = self._denied(request, "POST")
        if denied:
            return denied

        serializer = InviteCodeBatchCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        codes = create_codes(
            created_by=request.user,
            count=serializer.validated_data["count"],
            label_prefix=serializer.validated_data["label_prefix"],
            expires_at=serializer.validated_data.get("expires_at"),
        )
        return Response(
            InviteCodeAdminSerializer(codes, many=True).data,
            status=status.HTTP_201_CREATED,
        )


class InviteCodeAction(InviteAdminView):

    def _code(self, code_id):
        code = (
            InviteCode.objects.select_related("consumer__user")
            .filter(id=code_id)
            .first()
        )
        if code is None:
            return None, self.not_found()
        return code, None

    def _save_active(self, request, code_id, active: bool):
        denied = self._denied(request, "POST")
        if denied:
            return denied
        code, missing = self._code(code_id)
        if missing:
            return missing
        code.active = active
        code.save(update_fields=["active", "updated_at"])
        return Response(
            InviteCodeAdminSerializer(code).data,
            status=status.HTTP_200_OK,
        )


class InviteCodeRevoke(InviteCodeAction):

    def post(self, request, id):
        return self._save_active(request, id, False)


class InviteCodeReactivate(InviteCodeAction):

    def post(self, request, id):
        return self._save_active(request, id, True)


class InviteCodeReset(InviteCodeAction):

    def post(self, request, id):
        denied = self._denied(request, "POST")
        if denied:
            return denied
        code, missing = self._code(id)
        if missing:
            return missing
        try:
            code = reset_code(code)
        except ValidationError as exc:
            detail = exc.detail
            if isinstance(detail, list):
                detail = detail[0]
            return self.respond_with(str(detail), status_code=status.HTTP_400_BAD_REQUEST)
        return Response(
            InviteCodeAdminSerializer(code).data,
            status=status.HTTP_200_OK,
        )
