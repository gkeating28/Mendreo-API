#!/usr/bin/env bash
# Smoke-test Vercel API + Railway worker after hybrid deployment.
set -euo pipefail

API_URL="${1:-${VERCEL_API_URL:-https://mendreo-api.vercel.app}}"
WORKER_URL="${2:-${AI_WORKER_URL:-https://web-production-17436.up.railway.app}}"
INTERNAL_SECRET="${INTERNAL_API_SECRET:-}"

pass=0
fail=0

check() {
  local name="$1"
  local ok="$2"
  if [ "$ok" = "1" ]; then
    echo "OK   $name"
    pass=$((pass + 1))
  else
    echo "FAIL $name"
    fail=$((fail + 1))
  fi
}

echo "=== Mendreo hybrid deployment checks ==="
echo "API:    $API_URL"
echo "Worker: $WORKER_URL"
echo

api_health="$(curl -sS "$API_URL/" 2>/dev/null || true)"
echo "$api_health" | rg -q '"status"[[:space:]]*:[[:space:]]*"ok"' && check "Vercel health" 1 || check "Vercel health" 0

worker_health="$(curl -sS "$WORKER_URL/" 2>/dev/null || true)"
echo "$worker_health" | rg -q '"status"[[:space:]]*:[[:space:]]*"ok"' && check "Worker health" 1 || check "Worker health" 0

api_sessions_code="$(curl -sS -o /dev/null -w '%{http_code}' "$API_URL/sessions" 2>/dev/null || echo 000)"
[ "$api_sessions_code" = "401" ] && check "Vercel /sessions reachable (401 without auth)" 1 || check "Vercel /sessions reachable (got $api_sessions_code)" 0

worker_sessions_code="$(curl -sS -o /dev/null -w '%{http_code}' "$WORKER_URL/sessions" 2>/dev/null || echo 000)"
[ "$worker_sessions_code" = "401" ] && check "Worker /sessions reachable (401 without auth)" 1 || check "Worker /sessions reachable (got $worker_sessions_code)" 0

internal_no_auth="$(curl -sS -o /tmp/mendreo-internal-body.txt -w '%{http_code}' \
  -X POST "$WORKER_URL/internal/ai/message-response" \
  -H "Content-Type: application/json" \
  -d '{}' 2>/dev/null || echo 000)"

if [ "$internal_no_auth" = "404" ] && rg -q '<html' /tmp/mendreo-internal-body.txt 2>/dev/null; then
  check "Worker internal AI route (POST without secret → 403, not 404)" 0
  echo "      Hint: redeploy Railway from main — /internal/ routes missing (old build)."
elif [ "$internal_no_auth" = "403" ]; then
  check "Worker internal AI route (POST without secret → 403)" 1
else
  check "Worker internal AI route (expected 403, got $internal_no_auth)" 0
fi

if [ -n "$INTERNAL_SECRET" ]; then
  internal_bad_id="$(curl -sS -o /tmp/mendreo-internal-auth-body.txt -w '%{http_code}' \
    -X POST "$WORKER_URL/internal/ai/message-response" \
    -H "Content-Type: application/json" \
    -H "X-Internal-Secret: $INTERNAL_SECRET" \
    -d '{"user_message_id":"00000000-0000-0000-0000-000000000001"}' 2>/dev/null || echo 000)"
  if [ "$internal_bad_id" = "404" ] && ! rg -q '<html' /tmp/mendreo-internal-auth-body.txt 2>/dev/null; then
    check "Worker internal AI auth header accepted (DRF JSON 404 for missing message)" 1
  elif [ "$internal_bad_id" = "403" ]; then
    check "Worker internal AI auth header accepted (403 — check INTERNAL_API_SECRET on worker)" 0
  else
    check "Worker internal AI auth header accepted (got $internal_bad_id)" 0
  fi
else
  echo "SKIP internal auth probe (set INTERNAL_API_SECRET to test authenticated route)"
fi

echo
echo "Passed: $pass  Failed: $fail"
[ "$fail" -eq 0 ]
