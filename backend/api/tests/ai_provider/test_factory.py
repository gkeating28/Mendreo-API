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
            default_model="gemini-2.5-flash",
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
            "gemini-2.5-flash",
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
