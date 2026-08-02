# Mendreo V2 — Backend Implementation Plan

Tracked plan for implementing the backend services described in **Mendreo V2 Specification** (Personalisation, Exercises, Onboarding & Progress). Frontend/admin UI work is out of scope here except where API contracts are implied.

**Status:** Slices A–F implemented on branch  
**Source:** Mendreo V2 Spec (April 2026 draft)  
**Stack:** Django / DRF (`backend/api/`), Celery, Postgres (Supabase), existing AI provider layer

---

## 1. Goals

Deliver backend support for:

1. **User Knowledge Engine** — structured, auditable per-user knowledge with admin-configurable fields and gathering questions.
2. **Pre-Exercise Prompt** — exercise-level AI check-in for returning users, with session phase metadata.
3. **Onboarding & Refresh flows** — Initial / Return / Refresh variants with structured response controls, writing into the knowledge store.
4. **Progress & Insights** — mood, exercises, patterns (incl. AI observations), and streaks APIs.

---

## 2. Current baseline (gap analysis)

| Spec concept | Current state |
|---|---|
| Knowledge Fields / Questions / Entries | **Absent.** Closest: `Question` + `Attribute` (flat answers; no provenance, confidence, or history). |
| Pre-Exercise Prompt (AI check-in) | **Different concept exists:** `Question.pre_exercise` is a form-question flag, not an exercise-level AI prompt block. |
| Onboarding variants | Single flow via `GET /onboarding` + `Consumer.onboarded`. No Return / Refresh. |
| Progress / Mood / Streaks / Patterns | **Absent.** Closest: `Summary.observations` + 10-day session usage. |
| Knowledge permissions | **Absent.** `pii:view` exists for PII masking. |
| AI settings | `Setting` key/value (`survey_enabled`, prompts). Can host Observations config. |
| Background jobs | Celery daily summaries — pattern to reuse for observations + onboarding→knowledge backfill. |

Key packages today: `question`, `attribute`, `onboarding`, `survey`, `exercise`, `session`, `summary`, `setting`, `permissions`, `tasks`, `utils/Agent.py`.

---

## 3. Architectural decisions

### 3.1 Knowledge is a new domain (do not overload Attribute)

Introduce dedicated models under `backend/api/knowledge/`:

- Provenance (`source`), confidence, append-only history, and multi-source writes do not fit `Attribute`.
- Keep writing legacy `Attribute` during a transition period where onboarding still depends on it; derive or dual-write Knowledge Entries.

### 3.2 Pre-Exercise Prompt ≠ `Question.pre_exercise`

| Existing | V2 Spec |
|---|---|
| `Question.pre_exercise` — form questions cloned onto a session | Optional **block on `Exercise`**: description / instruction / goal / completion prompt / start button label |
| Completes via attribute answers | Conversational AI phase before Step 1; session stores summary + `completed_at` |

APIs must name the new fields explicitly (`pre_exercise_prompt_*`) so they do not collide with the question flag.

### 3.3 Conventions to follow

- One Django app (`api`); new domain packages with `models` / `serializers` / `views` / `urls`.
- Inherit `SmartModel` (soft delete, timestamps); IDs via `CharIDField` with prefixes.
- Migrations sequential in `backend/api/migrations/` (next after `0048`).
- RBAC via `Permissions` + `Constants`; enforce with `SmartAPIView` / `role_permission`.
- AI calls through existing `ai_provider` + `utils/Agent.py` / `utils/AI.py` patterns.
- Tests under `backend/api/tests/<domain>/`.

---

## 4. Delivery slices

Work is ordered by dependency. Each slice should land with migrations, serializers, views, URL wiring, and tests.

```
Slice A (Knowledge core)
    → Slice B (Knowledge runtime + admin user view)
        → Slice D (Onboarding flows)
            → Slice E (Progress)
Slice C (Pre-Exercise) can start after Slice A helpers for template resolution
```

### Slice A — Knowledge core + admin CRUD + permissions
**Spec:** §1.3–1.5, §1.8

- [x] Models: `KnowledgeField`, `KnowledgeQuestion`, `KnowledgeEntry`
- [x] Admin list/create/detail APIs for fields and questions
- [x] `POST .../test-extraction` dry-run endpoint
- [x] Extend `Permissions` with `knowledge` (`view` / `create` / `edit` / `delete`); update role defaults
- [x] Sensitive-field masking gated by existing `pii:view`
- [x] Celery backfill: onboarding `Attribute` → Knowledge Entries (`source=onboarding`)
- [x] Unit/API tests + migration

### Slice B — Per-user knowledge + chat integration
**Spec:** §1.4, §1.6–1.7

- [x] `GET/PATCH` consumer knowledge profile (grouped by category, current value, source, confidence, updated_at)
- [x] Entry history + activity feed (filter by source)
- [x] Admin edit value → new entry (`source=admin`)
- [x] Runtime service: `get_current_knowledge_summary(consumer)` for session start
- [x] Runtime write path: create entries from chat / extraction (`source=question` or `ai`) via `write_knowledge_entry`
- [x] Wire summary into Agent session context (read path)

### Slice C — Exercise Pre-Exercise Prompt
**Spec:** §2.3–2.7

- [x] Fields on `Exercise` for the pre-exercise prompt block (enabled + AI fields + start button label)
- [x] Fields on `Session`: `pre_exercise_prompt_summary`, `pre_exercise_completed_at`
- [x] Extend exercise serializers (create/update/list filter + enabled badge)
- [x] Extend session detail for check-in phase labeling / summary panel
- [x] `POST /exercises/<id>/test-pre-exercise-prompt` (resolve tokens; optional dry-run turn, no persist)
- [x] Session start: returning user + enabled → check-in phase before Step 1; handoff stamps completion
- [x] Publish validation: if enabled, Instruction + Goal required
- [x] Tests for create/update/duplicate/start/session detail
- [x] Cadence locked: **every repeat** (incl. same-day second runs); resume incomplete same-day session via `get_or_create` does not re-trigger
- [x] Handoff API: `POST /sessions/<id>/complete-pre-exercise`

### Slice D — Onboarding & Refresh flows
**Spec:** §3.2–3.8, §1 interaction

- [x] Question type `slider` (0–10) + anchor labels + value labels (11) on KnowledgeQuestion + legacy Question
- [x] Multi-select `min_selections` / `max_selections`
- [x] Flow variants: Initial / Return / Refresh (`flows` + `order_by_flow` on KnowledgeQuestion)
- [x] Refresh cadence setting `refresh_onboarding_cadence_days` (default 30)
- [x] Consumer APIs:
  - [x] `GET /onboarding/flow` (server-selected or `?variant=`)
  - [x] `POST /onboarding/answers` → Knowledge Entries (`source=question`) + onboarding/refresh state
  - [x] `GET /onboarding/status` for Home icon (`onboarded`, `refresh_due`, …)
- [x] Template resolution for prior answers (`{{knowledge.*}}`, `{{user.first_name}}`, …)
- [x] Initial: non-abandonable (`abandonable=false`; step sync allowed); Return/Refresh: discardable (complete-only)
- [x] Tests for variants, slider, constraints, knowledge writes
- [x] Open Q defaults: companion name `"Toni"` in payload (client-hardcode OK); Refresh not deferrable in v1 (dot → refresh)

### Slice E — Progress & Insights
**Spec:** §4.4–4.10

- [x] `GET /progress/mood` (range; gaps; avg / Δ / count)
- [x] `GET /progress/exercises` (completions, heatmap, breakdown)
- [x] `GET /progress/patterns` (observation card + top stress points)
- [x] `GET /progress/streaks` (check-in + exercise; Django TIME_ZONE v1; ignore range)
- [x] `UserObservation` model: text, topic tag, `generated_at`
- [x] Celery: generate observation ≤ once / 24h / user; retain prior on failure
- [x] Settings: Observations enabled / instruction / tone / max length
- [x] Stress points aggregated from `stress_points` multi-select answers in range
- [x] Tests for empty/sparse states and streak edge cases

### Slice F — Docs & contract freeze
- [x] Update `docs/API.md` with all new endpoints
- [x] Update `docs/API_DATABASE_DEEP_DIVE.md` for new models and write paths
- [x] Mark open questions resolved / deferred in this plan
- [x] Admin/mobile contract review checklist (see §12)

---

## 5. Proposed data model

### 5.1 KnowledgeField

| Field | Notes |
|---|---|
| `id` | `knf_` prefix |
| `key` | Stable machine key (unique) |
| `label` | Admin-facing label |
| `category` | Grouping for admin + profile panels |
| `value_type` | e.g. text / number / enum / multi — **confirm in open questions** |
| `sensitive` | Mask without `pii:view` |
| `active` | Default true |
| Soft-delete + timestamps | via `SmartModel` |

### 5.2 KnowledgeQuestion

| Field | Notes |
|---|---|
| `id` | `knq_` prefix |
| `prompt` | Question text; supports short template tokens |
| `target_field` | FK → KnowledgeField |
| `trigger` | `first_session` / `after_n_sessions` / `on_exercise_completion` / `manual_only` |
| `trigger_config` | JSON (e.g. `{ "n": 3 }`) |
| `suggested_responses` | Array (chips) |
| `extraction_prompt` | Maps reply → field value type |
| `flows` | Array: `initial` / `return` / `refresh` |
| `order_by_flow` | JSON map of variant → order, **or** join table — pick one in Slice D |
| `active` | Default true |

### 5.3 KnowledgeEntry

| Field | Notes |
|---|---|
| `id` | `kne_` prefix |
| `consumer` | FK |
| `field` | FK → KnowledgeField |
| `value` | Text / serialized structured value |
| `source` | `onboarding` / `question` / `ai` / `admin` |
| `confidence` | Float 0–1 (or decimal) |
| `knowledge_question` | Nullable FK (when source=question) |
| `session` | Nullable FK (when from chat/session) |
| `created_by_admin` | Nullable FK → Admin/User when source=admin |
| Timestamps | `created_at` is effective “written at”; current value = latest per (consumer, field) |

### 5.4 Exercise / Session additions

**Exercise**

- `pre_exercise_enabled` (bool, default true)
- `pre_exercise_description`
- `pre_exercise_instruction`
- `pre_exercise_goal`
- `pre_exercise_completion_prompt`
- `pre_exercise_start_button_label` (max 24, default `"Start exercise"`)

**Session**

- `pre_exercise_prompt_summary` (text, nullable)
- `pre_exercise_completed_at` (datetime, nullable)

### 5.5 Progress / Observations

**UserObservation** (recommended new model)

- `id` (`uobs_`), `consumer`, `text`, `topic_tag`, `generated_at`
- Retain last successful row when generation fails

**Settings keys**

- `observations_enabled`
- `observations_instruction`
- `observations_tone_guide`
- `observations_max_length`
- `refresh_onboarding_cadence_days` (Slice D)

### 5.6 Question type extensions (Slice D)

- New type: `slider` (0–10)
- Slider metadata: `anchor_labels` (2), `value_labels` (11)
- Multiple choice: optional `min_selections`, `max_selections`

---

## 6. Proposed API surface

Paths are indicative; final paths should match existing plural-resource style in `api/urls.py`.

### Knowledge (admin)

| Method | Path | Notes |
|---|---|---|
| GET, POST | `/knowledge-fields` | List/create; search + category + active filters |
| GET, PATCH, DELETE | `/knowledge-fields/<id>` | Detail |
| GET, POST | `/knowledge-questions` | List/create |
| GET, PATCH, DELETE | `/knowledge-questions/<id>` | Detail |
| POST | `/knowledge-questions/<id>/test-extraction` | Dry-run parse |

### Knowledge (per user)

| Method | Path | Notes |
|---|---|---|
| GET | `/consumers/<id>/knowledge` | Profile + optional activity |
| GET | `/consumers/<id>/knowledge/activity` | Feed, filter by source |
| GET | `/consumers/<id>/knowledge/fields/<field_id>/history` | Entry history |
| POST / PATCH | `/consumers/<id>/knowledge/entries` | Admin edit / runtime write |

### Exercises / sessions

| Method | Path | Notes |
|---|---|---|
| (extend) | `/exercises` | Pre-exercise fields; list filter `pre_exercise=all\|enabled\|disabled` |
| POST | `/exercises/<id>/test-pre-exercise-prompt` | Resolve + optional dry-run |
| (extend) | `/sessions/<id>` | `phase`, `pre_exercise` panel (summary + completed_at + start button) |
| (extend) | `/sessions/start` | Check-in phase for returning users (`current_step_no=0`) |
| POST | `/sessions/<id>/complete-pre-exercise` | Explicit Start handoff → Step 1 |

### Onboarding flows

| Method | Path | Notes |
|---|---|---|
| GET | `/onboarding` | Legacy Attribute-based payload (unchanged) |
| GET | `/onboarding/status` | `onboarded`, `refresh_due`, `recommended_variant`, cadence |
| GET | `/onboarding/flow` | Server-selected or `?variant=` KnowledgeQuestion sequence |
| POST | `/onboarding/answers` | Commit step (Initial) or full flow → knowledge entries |

### Progress

| Method | Path | Notes |
|---|---|---|
| GET | `/progress/mood?from=&to=` | Chart + summary strip |
| GET | `/progress/exercises?from=&to=` | Practice tab |
| GET | `/progress/patterns?from=&to=` | Observation + stress points |
| GET | `/progress/streaks` | All-time current + best |

### Roles

| Change | Notes |
|---|---|
| `Permissions.knowledge` | Levels: none / view / edit (map to existing view/edit patterns) |
| Role factories | Super Admin / Admin / Read Only defaults updated |

---

## 7. Background jobs

| Job | Trigger | Purpose |
|---|---|---|
| `backfill_knowledge_from_onboarding` | One-shot / re-runnable | Attributes → Knowledge Entries |
| `generate_user_observation` | Daily beat; fan-out per active user in overnight window | Patterns card content |
| (existing) `update_daily_summaries` | Unchanged | Chat summaries; may share transcript window helpers |
| (optional) `schedule_refresh_onboarding` | Daily | Mark consumers `refresh_due` from cadence |

Reuse Redis/Celery patterns in `backend/api/tasks.py` and `PeriodicTask` registration.

---

## 8. Permissions & compliance

- New resource: **Knowledge** — None / View Only / Edit.
- Existing **Personal Information (`pii`)** — None / View Only; masks sensitive knowledge fields and history.
- Activity feed must support filter by `source=ai` for compliance review.
- Every Knowledge Entry retains source + timestamp (+ confidence) for audit.

---

## 9. Interaction matrix (spec sections)

| From → To | Behaviour |
|---|---|
| Onboarding answers → Knowledge | Write Entry `source=question` (or `onboarding` for legacy backfill) |
| Return/Refresh copy → Knowledge | Read latest Entry values for template tokens |
| Chat session start → Knowledge | Inject current summary into model context |
| Chat / inference → Knowledge | Write Entry `source=ai` with confidence |
| Pre-Exercise → Knowledge | Read tokens; optional Entry from check-in summary |
| Progress Mood → Knowledge | Mood field Entries (slider) |
| Progress Patterns → Knowledge + sessions | Observation job + multi-select aggregation |
| Progress Exercises / Streaks → Sessions | Existing completed session records |

Pre-Exercise check-ins do **not** overlap onboarding flows (spec §3.8).

---

## 10. Open questions (block schema until decided)

Track decisions here before locking migrations.

| # | Question | Spec | Decision | Owner |
|---|---|---|---|---|
| 1 | Can admins manually push a knowledge question into a user’s next session? | §1.9 | **Deferred v1: no.** Triggers remain as configured; no admin push queue | Product |
| 2 | Tell users when AI uses remembered information? | §1.9 | **Deferred: client-only.** Backend exposes `source`/`confidence` on admin APIs; no consumer disclosure payload | Product |
| 3 | Pre-exercise: every repeat vs first repeat only? | §2.8 | **Every repeat** | Product |
| 4 | Skip pre-exercise if same exercise twice in one day? | §2.8 | **No skip** — same-day second runs still check in; incomplete same-day resume does not re-trigger | Product |
| 5 | Companion identity (“Toni”) — Settings vs hardcode? | §3.9 | Deferred: payload includes `companion_name: "Toni"`; client may hardcode avatar for launch | Product |
| 6 | Refresh deferrable (“Remind me later”)? | §3.9 | Deferred v1: not deferrable — Home dot launches Refresh | Product |
| 7 | Knowledge field value types (text/number/enum/multi)? | §1.3 | Deferred default: `text` / `number` / `boolean` / `single_choice` / `multiple_choice` (Slice A) | |
| 8 | Dual-write Attribute + Knowledge during transition, or cut over? | — | **Cut over for V2 flows.** `POST /onboarding/answers` writes Knowledge only; legacy Attribute path unchanged; backfill bridges | Backend |
| 9 | Coexistence strategy for legacy `Question.pre_exercise` form questions | §2 | Keep both; new fields named `pre_exercise_prompt_*` / session check-in phase — no rename of question flag | Backend |

---

## 11. Testing strategy

Per slice:

- Model constraints and soft-delete behaviour
- Serializer validation (publish rules, slider labels, multi-select bounds)
- Permission matrix (knowledge + pii masking)
- API happy path + empty/sparse Progress states
- Celery tasks with `CELERY_TASK_ALWAYS_EAGER` (existing local pattern)
- Regression: exercise duplicate, session start, existing onboarding `GET /onboarding`

Run:

```bash
cd backend && ../.venv/bin/python manage.py test api.tests
```

---

## 12. Docs & rollout checklist

- [x] This plan reviewed and open questions filled (remaining items deferred with defaults)
- [x] Slice A–F merged to `main` (PR #33)
- [x] Slice C implemented on branch (pre-exercise contracts stable for admin UI)
- [x] Slice D implemented on branch (mobile onboarding can integrate)
- [x] Slice E implemented on branch (Progress tabs can integrate)
- [x] `docs/API.md` + deep dive updated
- [ ] Staging: run migrations `0049–0052`, backfill job sampled for compliance
- [x] Feature flags / settings defaults confirmed (observations on, pre-exercise on for new exercises; existing exercises migrated off until authored)

### Admin / mobile contract checklist

- [ ] Admin: Knowledge Fields / Questions CRUD + test-extraction
- [ ] Admin: Exercise Pre-Exercise tab + list filter + test prompt
- [ ] Admin: Settings cadence + observations keys
- [ ] Mobile: `/onboarding/status|flow|answers` Initial → Home; Return/Refresh
- [ ] Mobile: session `phase` / `complete-pre-exercise` Start button
- [ ] Mobile: Progress tabs against `/progress/*` empty/sparse states

---

## 13. Suggested first PR after this plan

**Slice A only:** `api/knowledge/` models + migrations + admin CRUD + `knowledge` permission + extraction test stub + onboarding backfill task skeleton.

Do not start Progress or Pre-Exercise schema until open questions **3, 4, 7** are decided (or explicitly deferred with defaults documented in this file).

---

## 14. Reference map (existing files)

| Area | Path |
|---|---|
| URL hub | `backend/api/urls.py` |
| Questions / attributes | `backend/api/question/`, `backend/api/attribute/` |
| Onboarding / survey | `backend/api/onboarding/`, `backend/api/survey/` |
| Exercises / steps | `backend/api/exercise/`, `backend/api/step/` |
| Sessions / messages | `backend/api/session/`, `backend/api/message/` |
| Summaries | `backend/api/summary/`, `backend/api/exercise_summary/` |
| Settings | `backend/api/setting/` |
| Roles / permissions | `backend/api/role/`, `backend/api/permissions/`, `backend/api/utils/Constants.py` |
| Agent / AI | `backend/api/utils/Agent.py`, `backend/api/utils/AI.py` |
| Celery tasks | `backend/api/tasks.py` |
| API docs | `docs/API.md`, `docs/API_DATABASE_DEEP_DIVE.md` |
