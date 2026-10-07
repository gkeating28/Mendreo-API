from rest_framework.response import Response
from rest_framework import status

from ..utils.Constants import (
    CONSENT_AGE_STATEMENT,
    CONSENT_LIMITATIONS_STATEMENT,
    CONSENT_MARKETING_STATEMENT,
    CONSENT_VERSION,
)
from ..utils.Permissions import IsConsumerPermission
from ..utils.Views import SmartAPIView
from .access import has_current_consent
from .services import save_consent, validate_consent_payload


class Consent(SmartAPIView):
    """Current consent text, and the signed-in consumer's acceptance of it."""

    consent_exempt = True
    permission_classes = [IsConsumerPermission]

    def get(self, request):
        consumer = self.get_consumer_from_request()
        return Response(
            {
                "version": CONSENT_VERSION,
                "statements": {
                    "age_confirmed": CONSENT_AGE_STATEMENT,
                    "limitations_acknowledged": CONSENT_LIMITATIONS_STATEMENT,
                    "marketing_opt_in": CONSENT_MARKETING_STATEMENT,
                },
                "marketing_opt_in_default": False,
                "consent_required": not has_current_consent(consumer),
            },
            status=status.HTTP_200_OK,
        )

    def post(self, request):
        errors = validate_consent_payload(request.data)
        if errors:
            return Response({"detail": errors}, status=status.HTTP_400_BAD_REQUEST)

        consumer = self.get_consumer_from_request()
        opted_in = save_consent(consumer, request.data)
        return Response(
            {
                "version": CONSENT_VERSION,
                "age_confirmed": True,
                "limitations_acknowledged": True,
                "marketing_opt_in": opted_in,
                "consent_required": False,
            },
            status=status.HTTP_200_OK,
        )
