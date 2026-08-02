from unittest.mock import patch

from ..TestCase import TestCase
from ...ai_provider.models import AiProvider, AiProviderAuditLog
from ...utils import Constants
from ...utils.AiProviderFactory import AiProviderError, run_with_failover


class AiProviderFactoryTest(TestCase):

    def setUp(self):
        super().setUp()
        AiProvider.objects.all().delete()
        AiProviderAuditLog.objects.all().delete()

        self.google = AiProvider(
            name="Google",
            provider=Constants.AI_PROVIDER_GOOGLE,
            default_model="gemini-3.1-flash-lite",
            is_default=True,
            enabled=True,
        )
        self.google.set_api_key("google-secret")
        self.google.save()

        self.openai = AiProvider(
            name="OpenAI",
            provider=Constants.AI_PROVIDER_OPENAI,
            default_model="gpt-4.1-mini",
            is_default=False,
            enabled=True,
        )
        self.openai.set_api_key("openai-secret")
        self.openai.save()

    def test_resolve_model_falls_back_when_incompatible(self):
        self.assertEqual(
            self.google.resolve_model_name("gpt-4.1-mini"),
            "gemini-3.1-flash-lite",
        )
        self.assertEqual(
            self.openai.resolve_model_name("gpt-4.1"),
            "gpt-4.1",
        )

    def test_runtime_failover_logs_audit(self):
        calls = []

        def operation(provider):
            calls.append(provider.id)
            if provider.provider == Constants.AI_PROVIDER_GOOGLE:
                raise RuntimeError("google down")
            return {"ok": True, "provider": provider.provider}

        result, used = run_with_failover(operation)
        self.assertEqual(result["provider"], Constants.AI_PROVIDER_OPENAI)
        self.assertEqual(used.id, self.openai.id)
        self.assertEqual(calls, [self.google.id, self.openai.id])
        self.assertTrue(
            AiProviderAuditLog.objects.filter(
                action=Constants.AI_PROVIDER_AUDIT_FAILOVER,
                provider=self.openai,
            ).exists()
        )

    def test_all_providers_fail(self):
        def operation(_provider):
            raise RuntimeError("boom")

        with self.assertRaises(AiProviderError):
            run_with_failover(operation)

    def test_image_prefers_google(self):
        # Make OpenAI the global default; images should still use Google.
        AiProvider.clear_default_flags()
        self.openai.is_default = True
        self.openai.save()
        self.google.is_default = False
        self.google.save()

        image_provider = AiProvider.get_google_for_images()
        self.assertEqual(image_provider.id, self.google.id)

    def test_env_fallback_when_db_empty(self):
        import os

        from ...utils.AiProviderFactory import ensure_providers_ready

        AiProvider.objects.all().delete()
        previous = os.environ.get("GOOGLE_API_KEY")
        os.environ["GOOGLE_API_KEY"] = "env-fallback-key-9999"
        try:
            # Force DB seed to be skipped/useless by clearing again after placeholder setup
            AiProvider.objects.all().delete()
            # Even if DB seed encrypts successfully, we still accept DB or env.
            candidates = ensure_providers_ready()
            self.assertTrue(len(candidates) >= 1)
            self.assertEqual(candidates[0].get_api_key(), "env-fallback-key-9999")
        finally:
            if previous is None:
                os.environ.pop("GOOGLE_API_KEY", None)
            else:
                os.environ["GOOGLE_API_KEY"] = previous

    def test_env_fallback_when_db_keys_undecryptable(self):
        """Regression: undecryptable DB rows must not block GOOGLE_API_KEY fallback."""
        import os
        from unittest.mock import patch

        from django.core.exceptions import ImproperlyConfigured

        from ...utils.AiProviderFactory import ensure_providers_ready

        previous = os.environ.get("GOOGLE_API_KEY")
        os.environ["GOOGLE_API_KEY"] = "env-decrypt-fallback-4242"
        try:
            with patch.object(
                AiProvider,
                "get_api_key",
                side_effect=ImproperlyConfigured(
                    "AI_SECRETS_MASTER_KEY must be set to encrypt/decrypt AI provider keys."
                ),
            ):
                candidates = ensure_providers_ready()

            self.assertTrue(len(candidates) >= 1)
            self.assertTrue(all(getattr(c, "id", "").startswith("env_") for c in candidates))
            self.assertEqual(candidates[0].get_api_key(), "env-decrypt-fallback-4242")
        finally:
            if previous is None:
                os.environ.pop("GOOGLE_API_KEY", None)
            else:
                os.environ["GOOGLE_API_KEY"] = previous
