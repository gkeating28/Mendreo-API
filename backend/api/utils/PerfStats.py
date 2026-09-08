"""In-process rolling request latency samples for bottleneck diagnosis.

Each Vercel/Railway instance keeps its own window — use structured `perf`
logs for fleet-wide analysis; this summary is for quick live checks via
`GET /internal/perf/summary`.
"""
from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Deque, Dict, List, Tuple


@dataclass(frozen=True)
class PerfSample:
    method: str
    route: str
    status: int
    duration_ms: float
    db_ms: float
    db_queries: int
    ts: float


class PerfStats:
    def __init__(self, max_samples: int = 500) -> None:
        self._lock = threading.Lock()
        self._max_samples = max(50, int(max_samples))
        self._samples: Deque[PerfSample] = deque(maxlen=self._max_samples)

    def resize(self, max_samples: int) -> None:
        max_samples = max(50, int(max_samples))
        with self._lock:
            if max_samples == self._max_samples:
                return
            self._max_samples = max_samples
            self._samples = deque(self._samples, maxlen=max_samples)

    def record(self, sample: PerfSample) -> None:
        with self._lock:
            self._samples.append(sample)

    def clear(self) -> None:
        with self._lock:
            self._samples.clear()

    def summary(self, top_n: int = 15) -> dict:
        with self._lock:
            samples = list(self._samples)

        if not samples:
            return {
                "sample_count": 0,
                "window_seconds": 0,
                "overall": None,
                "slowest_routes": [],
                "recent_slow": [],
            }

        now = time.time()
        durations = [s.duration_ms for s in samples]
        db_ms = [s.db_ms for s in samples]
        by_route: Dict[Tuple[str, str], List[PerfSample]] = defaultdict(list)
        for sample in samples:
            by_route[(sample.method, sample.route)].append(sample)

        slowest = sorted(
            (
                {
                    "method": method,
                    "route": route,
                    "count": len(group),
                    "p50_ms": _percentile([s.duration_ms for s in group], 50),
                    "p95_ms": _percentile([s.duration_ms for s in group], 95),
                    "max_ms": round(max(s.duration_ms for s in group), 1),
                    "avg_db_ms": round(sum(s.db_ms for s in group) / len(group), 1),
                    "avg_db_queries": round(
                        sum(s.db_queries for s in group) / len(group), 1
                    ),
                }
                for (method, route), group in by_route.items()
            ),
            key=lambda row: row["p95_ms"],
            reverse=True,
        )[:top_n]

        recent_slow = [
            {
                "method": s.method,
                "route": s.route,
                "status": s.status,
                "duration_ms": round(s.duration_ms, 1),
                "db_ms": round(s.db_ms, 1),
                "db_queries": s.db_queries,
                "age_seconds": round(now - s.ts, 1),
            }
            for s in sorted(samples, key=lambda s: s.duration_ms, reverse=True)[:top_n]
        ]

        return {
            "sample_count": len(samples),
            "window_seconds": round(now - samples[0].ts, 1),
            "overall": {
                "p50_ms": _percentile(durations, 50),
                "p95_ms": _percentile(durations, 95),
                "p99_ms": _percentile(durations, 99),
                "max_ms": round(max(durations), 1),
                "avg_db_ms": round(sum(db_ms) / len(db_ms), 1),
                "avg_db_queries": round(
                    sum(s.db_queries for s in samples) / len(samples), 1
                ),
            },
            "slowest_routes": slowest,
            "recent_slow": recent_slow,
        }


def _percentile(values: List[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return round(ordered[0], 1)
    rank = (pct / 100.0) * (len(ordered) - 1)
    low = int(rank)
    high = min(low + 1, len(ordered) - 1)
    weight = rank - low
    return round(ordered[low] * (1 - weight) + ordered[high] * weight, 1)


# Process-wide singleton; resized from settings when middleware loads.
perf_stats = PerfStats()
