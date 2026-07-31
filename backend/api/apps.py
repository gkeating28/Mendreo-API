from django.apps import AppConfig


class ApiConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'api'

    def ready(self):
        from django.db.models.signals import post_migrate

        def _seed_ai_providers(sender, **kwargs):
            try:
                from .ai_provider.models import AiProvider
                AiProvider.seed_from_env_if_empty()
            except Exception:
                # Table may not exist yet mid-migrate, or master key missing in odd envs.
                pass

        post_migrate.connect(_seed_ai_providers, sender=self)
