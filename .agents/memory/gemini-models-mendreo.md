---
name: Gemini model choice for Mendreo chat
description: Latency benchmarks and thinking-config rules for the AI chat model; why the app stays on gemini-2.5-flash for now.
---

# Gemini model choice (benchmarked Jul 2026)

Chat model lives in DB: `api_agent.model` (Agent "Mendreo") — one-row change, no deploy.

Measured end-to-end POST /messages (structured output + tools via pydantic_ai):
- gemini-2.5-flash (thinking_budget=0): ~6s  ← kept
- gemini-3.1-flash-lite (minimal/low thinking): ~6.3-7.2s
- gemini-3-flash-preview: ~8-23s
- gemini-3.5-flash: ~7-22s, erratic

**Why:** 3.x models "think" by default and are slower on this workload even at
thinking_level minimal; no 3.x option beat 2.5-flash. 2.5 line retires ~Oct 2026,
so a forced migration is coming — streaming is the real UX fix.

**How to apply:**
- API model names: `gemini-3-flash-preview` (NOT `gemini-3-flash`), `gemini-3.5-flash`, `gemini-3.1-flash-lite`. List via client.models.list().
- 3.x rejects thinking_budget; use thinking_level (MINIMAL/LOW/MEDIUM/HIGH). 2.x uses thinking_budget. Branch on model name in Agent.py get_response.
- thinking_level needs google-genai >= ~1.4x (pinned 1.75.0; 1.39.1 raised pydantic extra_forbidden).
- Fallback reply "Sorry, I had an issue understanding your message" = swallowed exception in Agent.get_response (real error in `reasoning` field / logs).
