from django.test import SimpleTestCase, TestCase, override_settings
from rest_framework import status
from rest_framework.test import APIClient

from api.middleware.request_timing import normalize_route
from api.utils.PerfStats import PerfSample, PerfStats, perf_stats


class NormalizeRouteTest(SimpleTestCase):
    def test_strips_prefixed_ids(self):
        self.assertEqual(
            normalize_route("/sessions/ssn_abc123/messages/msg_xyz"),
            "/sessions/:id/messages/:id",
        )

    def test_strips_numeric_and_uuid(self):
        self.assertEqual(normalize_route("/items/42"), "/items/:id")
        self.assertEqual(
            normalize_route("/x/11111111-2222-3333-4444-555555555555"),
            "/x/:id",
        )

    def test_prefers_resolver_route(self):
        class _Match:
            route = "sessions/<pk>"

        self.assertEqual(
            normalize_route("/sessions/ssn_abc", _Match()),
            "/sessions/:id",
        )


class PerfStatsTest(SimpleTestCase):
    def test_percentile_summary(self):
        stats = PerfStats(max_samples=100)
        for i in range(10):
            stats.record(
                PerfSample(
                    method="GET",
                    route="/sessions",
                    status=200,
                    duration_ms=float(i * 10),
                    db_ms=1.0,
                    db_queries=2,
                    ts=1_700_000_000 + i,
                )
            )
        summary = stats.summary(top_n=5)
        self.assertEqual(summary["sample_count"], 10)
        self.assertEqual(summary["overall"]["p50_ms"], 45.0)
        self.assertEqual(summary["slowest_routes"][0]["route"], "/sessions")
        self.assertEqual(summary["slowest_routes"][0]["count"], 10)


@override_settings(INTERNAL_API_SECRET="test-internal-secret", PERF_LOG_ALL=True)
class RequestTimingMiddlewareTest(TestCase):
    """Uses Django TestCase so the full middleware stack runs against a real DB."""

    def setUp(self):
        super().setUp()
        perf_stats.clear()
        self.client = APIClient()

    def test_adds_timing_headers_on_api_response(self):
        response = self.client.get("/sessions")
        self.assertIn("Server-Timing", response)
        self.assertIn("app;dur=", response["Server-Timing"])
        self.assertIn("X-Response-Time", response)
        self.assertTrue(response["X-Response-Time"].endswith("ms"))
        self.assertIn("X-DB-Queries", response)

    def test_skips_health_paths(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertNotIn("Server-Timing", response)

    def test_perf_summary_requires_secret(self):
        denied = self.client.get("/internal/perf/summary")
        self.assertEqual(denied.status_code, status.HTTP_403_FORBIDDEN)

        self.client.get("/sessions")
        ok = self.client.get(
            "/internal/perf/summary",
            HTTP_X_INTERNAL_SECRET="test-internal-secret",
        )
        self.assertEqual(ok.status_code, status.HTTP_200_OK)
        body = ok.json()
        self.assertGreaterEqual(body["sample_count"], 1)
        self.assertIn("overall", body)
        self.assertIn("slowest_routes", body)
