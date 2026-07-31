from rest_framework import status

from ..TestCase import TestCase
from ..utils.manager import Auth
from ...ai_provider.models import AiProvider, AiProviderAuditLog
from ...utils import Constants
from ...utils.AiSecrets import decrypt_api_key


class AiProviderCrudTest(TestCase):

    def setUp(self):
        super().setUp()
        AiProvider.objects.all().delete()
        AiProviderAuditLog.objects.all().delete()

    def _create(self, data, access_token=None):
        return self._post("/ai-providers", data, access_token=access_token)

    def test_create_list_and_mask_key(self):
        token = Auth.get_platform_admin_access_token()
        response = self._create(
            {
                "name": "Gemini Prod",
                "provider": Constants.AI_PROVIDER_GOOGLE,
                "default_model": "gemini-2.5-flash",
                "is_default": True,
                "api_key": "sk-test-google-key-1234",
            },
            access_token=token,
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(response.data["has_api_key"])
        self.assertEqual(response.data["api_key_last4"], "…1234")
        self.assertNotIn("api_key", response.data)
        self.assertNotIn("api_key_encrypted", response.data)

        provider = AiProvider.objects.get(id=response.data["id"])
        self.assertEqual(decrypt_api_key(provider.api_key_encrypted), "sk-test-google-key-1234")
        self.assertTrue(
            AiProviderAuditLog.objects.filter(
                provider=provider, action=Constants.AI_PROVIDER_AUDIT_CREATED
            ).exists()
        )

        listing = self._get("/ai-providers", access_token=token)
        self.assertEqual(listing.status_code, status.HTTP_200_OK)

    def test_set_default_and_rotate_key(self):
        token = Auth.get_platform_admin_access_token()
        first = self._create(
            {
                "name": "Google",
                "provider": "google",
                "api_key": "google-key-aaaa",
                "is_default": True,
            },
            access_token=token,
        ).data
        second = self._create(
            {
                "name": "OpenAI",
                "provider": "openai",
                "default_model": "gpt-4.1-mini",
                "api_key": "openai-key-bbbb",
                "is_default": False,
            },
            access_token=token,
        ).data

        response = self._post(
            f"/ai-providers/{second['id']}/set-default",
            {},
            access_token=token,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["is_default"])
        self.assertFalse(AiProvider.objects.get(id=first["id"]).is_default)

        patch = self._patch(
            f"/ai-providers/{second['id']}",
            {"api_key": "openai-key-cccc"},
            access_token=token,
        )
        self.assertEqual(patch.status_code, status.HTTP_200_OK)
        self.assertEqual(patch.data["api_key_last4"], "…cccc")
        self.assertTrue(
            AiProviderAuditLog.objects.filter(
                provider_id=second["id"],
                action=Constants.AI_PROVIDER_AUDIT_KEY_ROTATED,
            ).exists()
        )

    def test_disable_default_auto_failover(self):
        token = Auth.get_platform_admin_access_token()
        first = self._create(
            {
                "name": "Google",
                "provider": "google",
                "api_key": "google-key-aaaa",
                "is_default": True,
            },
            access_token=token,
        ).data
        second = self._create(
            {
                "name": "OpenAI",
                "provider": "openai",
                "default_model": "gpt-4.1-mini",
                "api_key": "openai-key-bbbb",
            },
            access_token=token,
        ).data

        response = self._patch(
            f"/ai-providers/{first['id']}",
            {"enabled": False},
            access_token=token,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(AiProvider.objects.get(id=first["id"]).is_default)
        self.assertTrue(AiProvider.objects.get(id=second["id"]).is_default)

    def test_consumer_forbidden(self):
        response = self._create(
            {
                "name": "Google",
                "provider": "google",
                "api_key": "x",
            },
            access_token=Auth.get_consumer_access_token(),
        )
        self.permission_denied_test(response)

    def test_seed_from_env(self):
        AiProvider.objects.all().delete()
        with self.settings():
            import os
            os.environ["GOOGLE_API_KEY"] = "seed-google-zzzz"
            try:
                seeded = AiProvider.seed_from_env_if_empty()
                self.assertTrue(seeded)
                provider = AiProvider.objects.get(provider=Constants.AI_PROVIDER_GOOGLE)
                self.assertTrue(provider.is_default)
                self.assertEqual(provider.get_api_key(), "seed-google-zzzz")
            finally:
                os.environ.pop("GOOGLE_API_KEY", None)
