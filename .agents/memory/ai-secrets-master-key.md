---
name: AI_SECRETS_MASTER_KEY chat outage
description: Missing AI_SECRETS_MASTER_KEY on the Railway worker causes the frontend fallback "Sorry, I had an issue understanding your message"; real error is in message.reasoning.
---

# AI_SECRETS_MASTER_KEY (diagnosed Aug 2026)

Frontend fallback copy comes from `Agent.get_response` swallowing exceptions; real cause is in `api_message.reasoning`.

**Outage pattern (2026-08-02):**
`All AI providers failed: …/google: AI_SECRETS_MASTER_KEY must be set to encrypt/decrypt AI provider keys.`

DB had an `api_aiprovider` Google row with ciphertext, so the empty-table env fallback from PR #32 never ran. Worker lacked `AI_SECRETS_MASTER_KEY`, so decrypt failed and chat died.

**Fix (PR #37):**
- Skip undecryptable DB providers; fall back to `GOOGLE_API_KEY` env provider
- `manage.py seed_ai_providers --refresh-from-env` after setting a (new) master key
- Live Agent model: `gemini-3.1-flash-lite`

**Ops:** Keep `AI_SECRETS_MASTER_KEY` + `GOOGLE_API_KEY` on the Railway worker. Never rotate the Fernet key without re-encrypting DB keys.
