from django.test import RequestFactory, SimpleTestCase

from mendreo.middleware import PublicHostMiddleware
from mendreo.public_host import choose_public_host

DEPLOYMENT = "mendreo-qv8dlctfy-mendreo1.vercel.app"
ALIAS = "mendreo-api.vercel.app"


class ChoosePublicHostTests(SimpleTestCase):
    def test_replaces_loopback_with_the_forwarded_host(self):
        self.assertEqual(
            choose_public_host("127.0.0.1:54321", ALIAS, DEPLOYMENT),
            ALIAS,
        )

    def test_replaces_the_deployment_url(self):
        self.assertEqual(
            choose_public_host(DEPLOYMENT, ALIAS, DEPLOYMENT),
            ALIAS,
        )

    def test_keeps_a_public_host(self):
        self.assertEqual(choose_public_host(ALIAS, ALIAS, DEPLOYMENT), ALIAS)

    def test_does_not_let_a_forwarded_host_replace_a_public_host(self):
        self.assertEqual(
            choose_public_host(ALIAS, "evil.example", DEPLOYMENT),
            ALIAS,
        )

    def test_keeps_the_test_client_host(self):
        self.assertEqual(choose_public_host("testserver", "", ""), "testserver")


class PublicHostMiddlewareTests(SimpleTestCase):
    def test_absolute_uri_uses_the_public_https_host(self):
        request = RequestFactory().get(
            "/messages",
            {"session_id": "ssn_example"},
            HTTP_HOST="127.0.0.1:54321",
            HTTP_X_FORWARDED_HOST=ALIAS,
            HTTP_X_FORWARDED_PROTO="https",
            HTTP_X_VERCEL_DEPLOYMENT_URL=DEPLOYMENT,
        )
        PublicHostMiddleware(lambda req: req)(request)
        self.assertEqual(
            request.build_absolute_uri(),
            f"https://{ALIAS}/messages?session_id=ssn_example",
        )

    def test_ignores_a_forwarded_deployment_url_when_host_is_public(self):
        request = RequestFactory().get(
            "/messages",
            HTTP_HOST=ALIAS,
            HTTP_X_FORWARDED_HOST=DEPLOYMENT,
            HTTP_X_FORWARDED_PROTO="https",
            HTTP_X_VERCEL_DEPLOYMENT_URL=DEPLOYMENT,
        )
        PublicHostMiddleware(lambda req: req)(request)
        self.assertTrue(request.build_absolute_uri().startswith(f"https://{ALIAS}/"))

    def test_deployment_host_is_not_used_for_the_next_page(self):
        request = RequestFactory().get(
            "/messages",
            HTTP_HOST=DEPLOYMENT,
            HTTP_X_FORWARDED_HOST=ALIAS,
            HTTP_X_FORWARDED_PROTO="https",
            HTTP_X_VERCEL_DEPLOYMENT_URL=DEPLOYMENT,
        )
        PublicHostMiddleware(lambda req: req)(request)
        self.assertTrue(request.build_absolute_uri().startswith(f"https://{ALIAS}/"))
