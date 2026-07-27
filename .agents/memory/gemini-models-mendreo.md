---
name: Gemini model choice for Mendreo chat
description: Latency benchmarks and thinking-config rules for the AI chat model; current default is gemini-3.1-flash-lite.
---

# Gemini model choice (updated Jul 2026)

Chat model lives in DB: `api_agent.model` (Agent "Mendreo") — one-row change, no deploy.

**Current default:** `gemini-3.1-flash-lite` (as of 2026-07-27).

`gemini-2.5-flash` returns 404 for new API keys:
`This model models/gemini-2.5-flash is no longer available to new users.`
That surfaces as the fallback reply "Sorry, I had an issue understanding your message"
(real error in `api_message.reasoning`).

Earlier end-to-end POST /messages timings (structured output + tools via pydantic_ai):
- gemini-2.5-flash (thinking_budget=0): ~6s  ← retired for new keys
- gemini-3.1-flash-lite (minimal/low thinking): ~6.3-7.2s  ← current
- gemini-3-flash-preview: ~8-23s
- gemini-3.5-flash: ~7-22s, erratic
- Recommended Google replacement for 2.5-flash also includes `gemini-3.6-flash`

**How to apply:**
- API model names: `gemini-3.1-flash-lite`, `gemini-3.5-flash`, `gemini-3.6-flash`, `gemini-3-flash-preview` (NOT `gemini-3-flash`).
- 3.x rejects thinking_budget; use thinking_level (MINIMAL/LOW/MEDIUM/HIGH). 2.x uses thinking_budget. Branch on model name in Agent.py get_response.
- thinking_level needs google-genai >= ~1.4x (pinned 1.75.0; 1.39.1 raised pydantic extra_forbidden).
- Fallback reply "Sorry, I had an issue understanding your message" = swallowed exception in Agent.get_response (real error in `reasoning` field / logs).
