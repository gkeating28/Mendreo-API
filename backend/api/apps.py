import logging

from django.apps import AppConfig

logger = logging.getLogger(__name__)


class ApiConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'api'

    def ready(self):
        from django.db.models.signals import post_migrate

        def _seed_ai_providers(sender, **kwargs):
            try:
                from .ai_provider.models import AiProvider
                seeded = AiProvider.seed_from_env_if_empty()
                if seeded:
                    logger.info("post_migrate: seeded AI providers from environment")
            except Exception:
                # Table may not exist yet mid-migrate; never fail migrate itself.
                logger.exception(
                    "post_migrate: could not seed AI providers "
                    "(set AI_SECRETS_MASTER_KEY + GOOGLE_API_KEY on the worker)"
                )

        post_migrate.connect(_seed_ai_providers, sender=self)
