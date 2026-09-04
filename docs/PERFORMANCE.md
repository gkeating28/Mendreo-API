# Performance metrics & bottleneck diagnosis

How to tell whether slowness is **client render**, **API/DB**, or **AI worker**.

## What this API now exposes

| Signal | Where | Use |
|---|---|---|
| Structured `perf {...}` logs | Vercel / Railway runtime logs | Fleet-wide latency by route |
| `Server-Timing`, `X-Response-Time`, `X-DB-Queries` | Every API response (except `/`, `/healthz`) | Chrome DevTools → Network → Timing |
| `GET /internal/perf/summary` | In-process p50/p95 by route | Quick live check (per instance) |
| AI `response_time_in_sec` | `message.usage` / `session.usage` | Gemini-only latency |

### Example log line

```text
perf {"method":"GET","route":"/sessions/:id","path":"/sessions/ssn_abc","status":200,"duration_ms":182.4,"db_ms":95.1,"db_queries":12,"target":"vercel","slow":false,"raised":false}
```

Slow requests (`duration_ms >= PERF_SLOW_REQUEST_MS`, default 1000) log at WARNING.

### Live summary (authenticated)

```bash
curl -sS -H "X-Internal-Secret: $INTERNAL_API_SECRET" \
  "https://<api-host>/internal/perf/summary?top=20" | jq
```

Returns overall percentiles plus `slowest_routes` and `recent_slow`. Each Vercel/Railway instance has its own window — use logs for cross-instance analysis.

### Env knobs

| Variable | Default | Meaning |
|---|---|---|
| `PERF_SLOW_REQUEST_MS` | `1000` | WARNING threshold |
| `PERF_SAMPLE_SIZE` | `500` | In-process rolling sample size |
| `PERF_LOG_ALL` | `true` | Log every request; set `false` to log only slow/errors |

### Separating API wait from UI jank

In Chrome DevTools on `mendreo-web-app` / `mendreo-admin`:

1. Open **Network** → select an API call.
2. Read **Server Timing** (`app`, `db`) — that is backend time.
3. If Server Timing is small but the page still feels slow, the bottleneck is client-side (JS, images, hydration), not this API.

---

## Frontend: enable Vercel Speed Insights + Web Analytics

These repos are separate (`Mendreo-Web-App`, `Mendreo-Admin`) and not in this workspace. Apply the same change in both Next.js apps, then enable the products in the Vercel dashboard.

### 1. Dashboard (required once per project)

For **mendreo-web-app** and **mendreo-admin** on team **qula**:

1. Project → **Speed Insights** → Enable
2. Project → **Analytics** → Enable Web Analytics

Until both are enabled, packages report nothing useful.

### 2. Install packages

```bash
npm install @vercel/speed-insights @vercel/analytics
```

### 3. Mount in the root layout (App Router)

```tsx
// app/layout.tsx (or src/app/layout.tsx)
import { Analytics } from "@vercel/analytics/react";
import { SpeedInsights } from "@vercel/speed-insights/next";

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        {children}
        <Analytics />
        <SpeedInsights />
      </body>
    </html>
  );
}
```

### 4. Deploy and verify

After deploy, open the project’s **Speed Insights** (LCP / INP / CLS by route) and **Analytics** tabs. Correlate slow routes with API `perf` logs / `Server-Timing` for the same session.

---

## Suggested diagnosis workflow

1. Reproduce a slow screen with DevTools Network open.
2. Check API `Server-Timing`: high `db` → query/index work; high `app` with low `db` → Python/AI/proxy; low both → frontend.
3. Grep Vercel/Railway logs for `perf ` on that route.
4. Hit `/internal/perf/summary` on the worker/API during load tests.
5. Use Speed Insights p75 by route once frontend packages are live.
