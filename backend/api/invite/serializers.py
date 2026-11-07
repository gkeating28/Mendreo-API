from rest_framework import serializers

from .models import InviteCode
from .services import account_name, code_status, display_code


class InviteCodeBatchCreateSerializer(serializers.Serializer):
    count = serializers.IntegerField(min_value=1, max_value=50)
    label_prefix = serializers.CharField(allow_blank=True, max_length=200)
    expires_at = serializers.DateTimeField(required=False, allow_null=True)


class InviteCodeAdminSerializer(serializers.ModelSerializer):
    code = serializers.SerializerMethodField()
    status = serializers.SerializerMethodField()
    account_name = serializers.SerializerMethodField()

    class Meta:
        model = InviteCode
        fields = [
            "id",
            "code",
            "label",
            "expires_at",
            "active",
            "status",
            "redeemed_at",
            "account_name",
            "consumer_id",
            "created_at",
        ]

    def get_code(self, obj):
        return display_code(obj.code)

    def get_status(self, obj):
        return code_status(obj)

    def get_account_name(self, obj):
        return account_name(obj)
