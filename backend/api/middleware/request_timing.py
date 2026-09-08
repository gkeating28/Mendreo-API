"""Measure per-request wall time and DB cost; emit structured perf logs.

Also sets ``Server-Timing`` / ``X-Response-Time`` so browser DevTools and
frontends can attribute wait time to the API vs client render.
"""
from __future__ import annotations

import json
import logging
import re
import time
from typing import Callable

from django.conf import settings
from django.db import connection
from django.http import HttpRequest, HttpResponse

from api.utils.PerfStats import PerfSample, perf_stats

logger = logging.getLogger("api.perf")

_HEALTH_PATHS = frozenset({"/", "/healthz"})
# Prefixed char IDs (msg_..., ssn_..., etc.) and bare UUIDs / numeric PKs.
_ID_SEGMENT = re.compile(
    r"(?<=/)"
    r"(?:"
    r"[a-z]{2,12}_[A-Za-z0-9]+"
    r"|[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
    r"|[0-9]+"
    r")"
    r"(?=/|$)"
)


class _QueryCounter:
    __slots__ = ("count", "total_ms")

    def __init__(self) -> None:
        self.count = 0
        self.total_ms = 0.0

    def __call__(self, execute, sql, params, many, context):
        self.count += 1
        started = time.perf_counter()
        try:
            return execute(sql, params, many, context)
        finally:
            self.total_ms += (time.perf_counter() - started) * 1000.0


def normalize_route(path: str, resolver_match=None) -> str:
    """Collapse resource IDs so metrics group by endpoint, not instance."""
    if resolver_match is not None:
        route = getattr(resolver_match, "route", None)
        if route:
            # Django route strings look like "sessions/<pk>" or "^sessions/(?P<pk>[^/.]+)/$"
            cleaned = route.strip("^$")
            cleaned = re.sub(r"\(\?P<[^>]+>[^)]+\)", ":id", cleaned)
            cleaned = re.sub(r"<[^>]+>", ":id", cleaned)
            if not cleaned.startswith("/"):
                cleaned = f"/{cleaned}"
            return cleaned.rstrip("/") or "/"
    normalized = _ID_SEGMENT.sub(":id", path or "/")
    return normalized.rstrip("/") or "/"


class RequestTimingMiddleware:
    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response
        max_samples = int(getattr(settings, "PERF_SAMPLE_SIZE", 500))
        perf_stats.resize(max_samples)

    def __call__(self, request: HttpRequest) -> HttpResponse:
        path = request.path or "/"
        if path in _HEALTH_PATHS:
            return self.get_response(request)

        counter = _QueryCounter()
        started = time.perf_counter()
        try:
            with connection.execute_wrapper(counter):
                response = self.get_response(request)
        except Exception:
            duration_ms = (time.perf_counter() - started) * 1000.0
            self._emit(
                request=request,
                status=500,
                duration_ms=duration_ms,
                db_ms=counter.total_ms,
                db_queries=counter.count,
                raised=True,
            )
            raise

        duration_ms = (time.perf_counter() - started) * 1000.0
        self._emit(
            request=request,
            status=getattr(response, "status_code", 0),
            duration_ms=duration_ms,
            db_ms=counter.total_ms,
            db_queries=counter.count,
            raised=False,
        )
        self._set_timing_headers(response, duration_ms, counter)
        return response

    def _emit(
        self,
        *,
        request: HttpRequest,
        status: int,
        duration_ms: float,
        db_ms: float,
        db_queries: int,
        raised: bool,
    ) -> None:
        route = normalize_route(request.path, getattr(request, "resolver_match", None))
        method = request.method or "GET"
        sample = PerfSample(
            method=method,
            route=route,
            status=status,
            duration_ms=duration_ms,
            db_ms=db_ms,
            db_queries=db_queries,
            ts=time.time(),
        )
        perf_stats.record(sample)

        slow_ms = float(getattr(settings, "PERF_SLOW_REQUEST_MS", 1000))
        log_all = bool(getattr(settings, "PERF_LOG_ALL", True))
        is_slow = duration_ms >= slow_ms or raised
        if not log_all and not is_slow:
            return

        payload = {
            "method": method,
            "route": route,
            "path": request.path,
            "status": status,
            "duration_ms": round(duration_ms, 1),
            "db_ms": round(db_ms, 1),
            "db_queries": db_queries,
            "target": getattr(settings, "DEPLOYMENT_TARGET", "local"),
            "slow": is_slow,
            "raised": raised,
        }
        line = f"perf {json.dumps(payload, separators=(',', ':'))}"
        if is_slow:
            logger.warning(line)
        else:
            logger.info(line)

    @staticmethod
    def _set_timing_headers(
        response: HttpResponse, duration_ms: float, counter: _QueryCounter
    ) -> None:
        # Server-Timing is visible in Chrome DevTools → Network → Timing.
        response["Server-Timing"] = (
            f"app;dur={duration_ms:.1f},"
            f"db;dur={counter.total_ms:.1f};desc=\"db {counter.count}q\""
        )
        response["X-Response-Time"] = f"{duration_ms:.1f}ms"
        response["X-DB-Queries"] = str(counter.count)
