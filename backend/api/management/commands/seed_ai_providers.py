import os

from django.core.management.base import BaseCommand, CommandError

from api.ai_provider.models import AiProvider, AiProviderAuditLog
from api.utils import Api, Constants


class Command(BaseCommand):
    help = (
        "Seed AI providers from GOOGLE_API_KEY / OPENAI_API_KEY / ANTHROPIC_API_KEY "
        "when none exist, or refresh encrypted keys from env with --refresh-from-env."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--refresh-from-env",
            action="store_true",
            help=(
                "Re-encrypt existing provider API keys from matching env vars "
                "(requires AI_SECRETS_MASTER_KEY). Creates missing providers."
            ),
        )

    def handle(self, *args, **options):
        if options["refresh_from_env"]:
            self._refresh_from_env()
            return

        seeded = AiProvider.seed_from_env_if_empty()
        if seeded:
            self.stdout.write(self.style.SUCCESS("Seeded AI providers from environment."))
        else:
            count = AiProvider.objects.count()
            self.stdout.write(f"No seed performed (existing providers: {count}).")

    def _refresh_from_env(self):
        env_keys = {
            Constants.AI_PROVIDER_GOOGLE: (
                os.environ.get("GOOGLE_API_KEY", "").strip()
                or (Api.GOOGLE_API_KEY or "").strip()
            ),
            Constants.AI_PROVIDER_OPENAI: os.environ.get("OPENAI_API_KEY", "").strip(),
            Constants.AI_PROVIDER_ANTHROPIC: os.environ.get("ANTHROPIC_API_KEY", "").strip(),
        }
        names = {
            Constants.AI_PROVIDER_GOOGLE: "Google Gemini",
            Constants.AI_PROVIDER_OPENAI: "OpenAI",
            Constants.AI_PROVIDER_ANTHROPIC: "Anthropic",
        }

        if not any(env_keys.values()):
            raise CommandError(
                "No GOOGLE_API_KEY / OPENAI_API_KEY / ANTHROPIC_API_KEY found in environment."
            )

        updated = 0
        created = 0
        has_default = AiProvider.objects.filter(is_default=True, enabled=True).exists()

        for provider_type, key in env_keys.items():
            if not key:
                continue

            row = (
                AiProvider.objects.filter(provider=provider_type, enabled=True)
                .order_by("-is_default", "created_at")
                .first()
            )
            if row:
                row.set_api_key(key)
                row.save(update_fields=["api_key_encrypted", "updated_at"])
                AiProviderAuditLog.log(
                    provider=row,
                    action=Constants.AI_PROVIDER_AUDIT_KEY_ROTATED,
                    actor=None,
                    detail={"source": "refresh_from_env"},
                )
                updated += 1
                self.stdout.write(f"Updated API key for {row.name} ({provider_type}).")
            else:
                is_default = not has_default and provider_type == Constants.AI_PROVIDER_GOOGLE
                row = AiProvider(
                    name=names[provider_type],
                    provider=provider_type,
                    default_model=Constants.AI_PROVIDER_DEFAULT_MODELS[provider_type],
                    is_default=is_default,
                    enabled=True,
                )
                row.set_api_key(key)
                row.save()
                if is_default:
                    has_default = True
                AiProviderAuditLog.log(
                    provider=row,
                    action=Constants.AI_PROVIDER_AUDIT_SEEDED,
                    actor=None,
                    detail={"source": "refresh_from_env"},
                )
                created += 1
                self.stdout.write(f"Created {row.name} ({provider_type}) from environment.")

        self.stdout.write(
            self.style.SUCCESS(
                f"Refresh complete (updated={updated}, created={created})."
            )
        )
