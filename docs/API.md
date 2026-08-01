# Mendreo API Reference

Base URL: your dev URL (Replit `.replit.dev`) in development, or your `.replit.app` domain in production. All paths below are relative.

> For a deep dive into the models behind each endpoint and exactly how each one reads from and writes to the database (including the shared `Smart*` view machinery, soft-deletes, transactions, PII obscuring, and the session/message/LLM/upload/subscription flows), see [`API_DATABASE_DEEP_DIVE.md`](./API_DATABASE_DEEP_DIVE.md).

## Conventions (from the `Smart*` base views)

- **Auth**: Most endpoints require a JWT bearer token. Permission classes distinguish Admin vs Consumer access.
- **Collection pattern**: Resources marked *list/create + detail* expose `GET` (list, paginated) and `POST` (create) on the collection, and `GET` / `PATCH` / `DELETE` on `/<id>`.
- **Pagination**: List endpoints use cursor pagination by default. Use `?pagination_type=page` for page-based pagination. Supports `page_size` and `order_by` query params.
- **PII obscuring**: Admins without the `pii:view` permission receive anonymized `first_name`, `last_name`, `email`, and `date_of_birth` in responses.

---

## Authentication & User — `/user`

| Method | Path | Function |
|---|---|---|
| POST | `/user/login` | Email/password login → returns JWT pair |
| POST | `/user/login/` (+ social) | Social login (Google/Apple) via `rest_social_auth`, returns JWT |
| GET | `/user/facebook-code` | Facebook OAuth code exchange |
| POST | `/user/logout` | Invalidate session/token |
| POST | `/user/refresh-token` | Exchange refresh token for new access token |
| GET | `/user/info` | Current authenticated user's profile |
| POST | `/user/request-reset-password` | Email a password-reset code |
| POST | `/user/reset-password` | Reset password using the code |
| POST | `/user/request-verify-email` | Email an account-verification code |
| POST | `/user/verify-email` | Confirm email with the code |

---

## Core Resources (list/create + detail)

Each follows the uniform pattern: `GET` (list, paginated) and `POST` (create) on the collection; `GET` / `PATCH` / `DELETE` on `/<id>`.

| Resource | Collection path | Item path |
|---|---|---|
| Agents (therapists/coaches) | `GET,POST /agents` | `GET,PATCH,DELETE /agents/<id>` |
| Admins | `GET,POST /admins` | `GET,PATCH,DELETE /admins/<id>` |
| Consumers (end users) | `GET,POST /consumers` | `GET,PATCH,DELETE /consumers/<id>` |
| Roles (permissions) | `GET,POST /roles` | `GET,PATCH,DELETE /roles/<id>` |
| Posts | `GET,POST /posts` | `GET,PATCH,DELETE /posts/<id>` |
| Questions | `GET,POST /questions` | `GET,PATCH,DELETE /questions/<id>` |
| Attributes | `GET,POST /attributes` | `GET,PATCH,DELETE /attributes/<id>` |
| Packages (plans) | `GET,POST /packages` | `GET,PATCH,DELETE /packages/<id>` |
| Tags | `GET,POST /tags` | `GET,PATCH,DELETE /tags/<id>` |
| Assets (media/content) | `GET,POST /assets` | `GET,PATCH,DELETE /assets/<id>` |

---

## Sessions — `/sessions`

| Method | Path | Function |
|---|---|---|
| GET | `/sessions` | List sessions (paginated) |
| GET | `/sessions/today` | Today's session for the consumer |
| GET | `/sessions/start` | Start/initialize a new session |
| GET, PATCH, DELETE | `/sessions/<id>` | Retrieve / update / delete a session |
| GET | `/sessions/<id>/summary` | Generated summary of a session |

---

## Messages & Summaries

| Method | Path | Function |
|---|---|---|
| GET, POST | `/messages` | List messages / send a message (drives the AI conversation) |
| GET | `/summaries/<id>` | Retrieve a summary |

**Async AI (Vercel):** `POST /messages` creates the user message, enqueues Gemini on the worker via Celery, and returns the user message with `ai_pending: true`. Poll `GET /messages?session_id=<id>` (or `GET /sessions/<id>`) until the agent reply appears as `last_message`. Local/dev defaults to synchronous replies unless `AI_ASYNC_MESSAGES=true`.

---

## Exercises

| Method | Path | Function |
|---|---|---|
| GET, POST | `/exercises` | List / create exercises |
| POST | `/exercises/duplicate` | Duplicate an existing exercise |
| GET, PATCH, DELETE | `/exercises/<id>` | Retrieve / update / delete |
| GET, PATCH, DELETE | `/exercise-summaries/<id>` | Retrieve / update / delete an exercise summary |

> Note: the `exercise_summary` module also defines a list/create view, but only the `/<id>` route is wired in its `urls.py` — the collection route is not currently exposed.

---

## AI, Feedback, Onboarding, Survey

| Method | Path | Function |
|---|---|---|
| GET, POST | `/ai` | AI generation/inference endpoint |
| GET, POST | `/feedback` | Submit feedback |
| GET | `/onboarding` | Onboarding flow data |
| GET | `/survey` | Survey questions/data |

---

## Knowledge (V2 Slices A–B)

Admin-only. Role permission resource: `knowledge`. Sensitive entry values are masked as `"Restricted"` when the admin lacks `pii:view`.

### Configuration

| Method | Path | Function |
|---|---|---|
| GET, POST | `/knowledge-fields` | List / create knowledge field definitions |
| GET, PATCH, DELETE | `/knowledge-fields/<id>` | Retrieve / update / soft-delete a field |
| GET, POST | `/knowledge-questions` | List / create knowledge gathering questions |
| GET, PATCH, DELETE | `/knowledge-questions/<id>` | Retrieve / update / soft-delete a question |
| POST | `/knowledge-questions/<id>/test-extraction` | Dry-run extraction prompt against a sample reply |
| GET, POST | `/knowledge-entries` | List / create per-user knowledge entries (append-only history) |
| GET, DELETE | `/knowledge-entries/<id>` | Retrieve / soft-delete an entry |

Filters: fields support `search_term`, `category`, `active`; questions support `search_term`, `active`, `target_field_id`, `trigger`, `flow`; entries support `consumer_id`, `field_id`, `source`.

### Per-user knowledge (admin portal)

| Method | Path | Function |
|---|---|---|
| GET | `/consumers/<id>/knowledge` | Profile grouped by category (current value, source, confidence, updated_at) |
| PATCH | `/consumers/<id>/knowledge` | Admin edit: body `{field_id, value}` or `{entries: [...]}` — appends `source=admin` entries |
| GET | `/consumers/<id>/knowledge/activity` | Chronological feed; filter `?source=` |
| GET | `/consumers/<id>/knowledge/fields/<field_id>/history` | Field history (blocked/empty when sensitive + no `pii:view`) |

Chat session prompts include the current knowledge summary via `get_current_knowledge_summary`. Writes go through `write_knowledge_entry` (invalidates that consumer’s `session.cached_prompt`).

Celery task `backfill_knowledge_from_onboarding` creates entries from onboarding `Attribute` answers matched by `KnowledgeField.key`.

See also [`V2_BACKEND_IMPLEMENTATION_PLAN.md`](./V2_BACKEND_IMPLEMENTATION_PLAN.md).

---

## Subscriptions & Settings

| Method | Path | Function |
|---|---|---|
| GET, PATCH, DELETE | `/subscriptions/<id>` | Manage a subscription (Stripe-backed) |
| GET, POST | `/settings` | Read / write app settings |

---

## Files & Images (uploads)

| Method | Path | Function |
|---|---|---|
| POST | `/files` | Upload a file (returns a presigned Supabase Storage upload link) |
| GET, PATCH, DELETE | `/files/<id>` | Manage a file record |
| POST | `/images` | Upload an image |
| GET, PATCH, DELETE | `/images/<id>` | Manage an image record |

---

## Misc

| Method | Path | Function |
|---|---|---|
| GET | `/` | Health/status JSON |
| GET | `/__debug__/...` | Django Debug Toolbar (only when `DEBUG=True`) |
