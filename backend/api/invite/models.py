from django.db import models

from ..consumer.models import Consumer
from ..user.models import User
from ..utils.Fields import CharIDField
from ..utils.Models import SmartModel


class InviteCode(SmartModel):
    """One access code. The first redemption creates exactly one account."""

    id = CharIDField(primary_key=True, prefix="ivc_")

    # Eight uppercase characters, no dash. Display form is XXXX-XXXX.
    code = models.CharField(max_length=8, unique=True)

    label = models.CharField(max_length=255, blank=True, default="")

    expires_at = models.DateTimeField(null=True, blank=True)

    active = models.BooleanField(default=True, db_default=True)

    consumer = models.OneToOneField(
        Consumer,
        related_name="invite_code",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )

    redeemed_at = models.DateTimeField(null=True, blank=True)

    created_by = models.ForeignKey(
        User,
        related_name="invite_codes_created",
        on_delete=models.PROTECT,
    )

    def __str__(self):
        return f"InviteCode: {self.code}"

    def get_permission_key(self, view=None):
        # A code is an account, so it uses the existing users permission.
        return "users"
