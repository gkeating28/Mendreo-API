from rest_framework import serializers

from .models import AiProvider, AiProviderAuditLog
from ..utils import Constants
from ..utils.Serializers import (
    CreateModelSerializer,
    EditModelSerializer,
    ListModelSerializer,
)


class AiProviderListSerializer(ListModelSerializer):
    has_api_key = serializers.SerializerMethodField()
    api_key_last4 = serializers.SerializerMethodField()
    suggested_models = serializers.SerializerMethodField()

    class Meta:
        model = AiProvider
        fields = [
            "id",
            "name",
            "provider",
            "default_model",
            "is_default",
            "enabled",
            "has_api_key",
            "api_key_last4",
            "suggested_models",
            "extra_config",
            "created_at",
            "updated_at",
        ]

    def get_has_api_key(self, obj: AiProvider) -> bool:
        return obj.has_api_key()

    def get_api_key_last4(self, obj: AiProvider):
        return obj.api_key_last4()

    def get_suggested_models(self, obj: AiProvider):
        return Constants.AI_PROVIDER_SUGGESTED_MODELS.get(obj.provider, [])


class AiProviderDetailSerializer(AiProviderListSerializer):
    class Meta(AiProviderListSerializer.Meta):
        fields = AiProviderListSerializer.Meta.fields


class AiProviderCreateSerializer(CreateModelSerializer):
    api_key = serializers.CharField(write_only=True, allow_blank=False)
    provider = serializers.ChoiceField(choices=[(p, p) for p in Constants.AI_PROVIDERS])
    default_model = serializers.CharField(required=False, allow_blank=False)
    is_default = serializers.BooleanField(required=False, default=False)
    enabled = serializers.BooleanField(required=False, default=True)
    extra_config = serializers.JSONField(required=False, default=dict)

    class Meta:
        model = AiProvider
        fields = [
            "name",
            "provider",
            "default_model",
            "is_default",
            "enabled",
            "api_key",
            "extra_config",
        ]

    def validate_provider(self, value):
        if value not in Constants.AI_PROVIDERS:
            self.raise_validation_error(
                "provider", f"provider needs to be one of {Constants.AI_PROVIDERS}"
            )
        return value

    def validate(self, attrs):
        provider_type = attrs.get("provider")
        if not attrs.get("default_model"):
            attrs["default_model"] = Constants.AI_PROVIDER_DEFAULT_MODELS[provider_type]
        return attrs

    def create(self, validated_data):
        api_key = validated_data.pop("api_key")
        actor = self.context.get("actor")

        making_default = validated_data.get("is_default", False)
        if making_default:
            AiProvider.clear_default_flags()

        # If this is the first provider, force default
        if not AiProvider.objects.exists():
            validated_data["is_default"] = True
            making_default = True

        instance = AiProvider(**validated_data)
        instance.set_api_key(api_key)
        instance.save()

        AiProviderAuditLog.log(
            provider=instance,
            action=Constants.AI_PROVIDER_AUDIT_CREATED,
            actor=actor,
            detail={"is_default": instance.is_default},
        )
        if making_default:
            AiProviderAuditLog.log(
                provider=instance,
                action=Constants.AI_PROVIDER_AUDIT_SET_DEFAULT,
                actor=actor,
                detail={},
            )
        return instance


class AiProviderEditSerializer(EditModelSerializer):
    api_key = serializers.CharField(write_only=True, required=False, allow_blank=False)
    default_model = serializers.CharField(required=False, allow_blank=False)
    is_default = serializers.BooleanField(required=False)
    enabled = serializers.BooleanField(required=False)
    name = serializers.CharField(required=False, allow_blank=False)
    extra_config = serializers.JSONField(required=False)

    class Meta:
        model = AiProvider
        fields = [
            "name",
            "default_model",
            "is_default",
            "enabled",
            "api_key",
            "extra_config",
        ]

    def update(self, instance: AiProvider, validated_data):
        actor = self.context.get("actor")
        api_key = validated_data.pop("api_key", None)
        previous_default = instance.is_default
        previous_enabled = instance.enabled

        making_default = validated_data.get("is_default", instance.is_default)
        enabling = validated_data.get("enabled", instance.enabled)

        if making_default is True:
            AiProvider.clear_default_flags(except_id=instance.id)

        if api_key is not None:
            instance.set_api_key(api_key)

        for field, value in validated_data.items():
            setattr(instance, field, value)

        instance.save()

        AiProviderAuditLog.log(
            provider=instance,
            action=Constants.AI_PROVIDER_AUDIT_UPDATED,
            actor=actor,
            detail={"fields": list(validated_data.keys()) + (["api_key"] if api_key else [])},
        )

        if api_key is not None:
            AiProviderAuditLog.log(
                provider=instance,
                action=Constants.AI_PROVIDER_AUDIT_KEY_ROTATED,
                actor=actor,
                detail={},
            )

        if making_default and not previous_default:
            AiProviderAuditLog.log(
                provider=instance,
                action=Constants.AI_PROVIDER_AUDIT_SET_DEFAULT,
                actor=actor,
                detail={},
            )

        if previous_enabled and enabling is False:
            AiProviderAuditLog.log(
                provider=instance,
                action=Constants.AI_PROVIDER_AUDIT_DISABLED,
                actor=actor,
                detail={},
            )
            if instance.is_default or previous_default:
                # Disabled default → promote another enabled provider
                instance.is_default = False
                instance.save(update_fields=["is_default", "updated_at"])
                AiProvider.promote_failover_default(excluding_id=instance.id, actor=actor)

        if (not previous_enabled) and enabling is True:
            AiProviderAuditLog.log(
                provider=instance,
                action=Constants.AI_PROVIDER_AUDIT_ENABLED,
                actor=actor,
                detail={},
            )

        return instance


class AiProviderAuditLogSerializer(ListModelSerializer):
    class Meta:
        model = AiProviderAuditLog
        fields = [
            "id",
            "provider",
            "provider_id_snapshot",
            "provider_name_snapshot",
            "provider_type_snapshot",
            "actor",
            "action",
            "detail",
            "created_at",
        ]
