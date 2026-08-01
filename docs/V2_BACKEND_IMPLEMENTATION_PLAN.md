# Mendreo V2 — Backend Implementation Plan

Tracked plan for implementing the backend services described in **Mendreo V2 Specification** (Personalisation, Exercises, Onboarding & Progress). Frontend/admin UI work is out of scope here except where API contracts are implied.

**Status:** Slices A–B implemented on branch; later slices pending  
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

- [ ] Fields on `Exercise` for the pre-exercise prompt block (enabled + AI fields + start button label)
- [ ] Fields on `Session`: `pre_exercise_prompt_summary`, `pre_exercise_completed_at`
- [ ] Extend exercise serializers (create/update/list filter + enabled badge)
- [ ] Extend session detail for check-in phase labeling / summary panel
- [ ] `POST /exercises/<id>/test-pre-exercise-prompt` (resolve tokens; optional dry-run turn, no persist)
- [ ] Session start: returning user + enabled → check-in phase before Step 1; handoff stamps completion
- [ ] Publish validation: if enabled, Instruction + Goal required
- [ ] Tests for create/update/duplicate/start/session detail

### Slice D — Onboarding & Refresh flows
**Spec:** §3.2–3.8, §1 interaction

- [ ] Question type `slider` (0–10) + anchor labels + value labels (11)
- [ ] Multi-select `min_selections` / `max_selections`
- [ ] Flow variants: Initial / Return / Refresh (membership + per-variant order on knowledge/onboarding questions)
- [ ] Refresh cadence setting (e.g. days) driving Home “due” state
- [ ] Consumer APIs:
  - [ ] Flow payload (server-selected or `?variant=`)
  - [ ] Answer submit → Knowledge Entries (`source=question`) + onboarding/refresh state
  - [ ] Status for Home icon (`onboarded`, `refresh_due`, …)
- [ ] Template resolution for prior answers (“last time you said…”)
- [ ] Initial: non-abandonable (server or accepted client persistence); Return: discardable
- [ ] Tests for variants, slider, constraints, knowledge writes

### Slice E — Progress & Insights
**Spec:** §4.4–4.10

- [ ] `GET /progress/mood` (range; gaps; avg / Δ / count)
- [ ] `GET /progress/exercises` (completions, heatmap, breakdown)
- [ ] `GET /progress/patterns` (observation card + top stress points)
- [ ] `GET /progress/streaks` (check-in + exercise; user TZ; ignore range)
- [ ] `UserObservation` (or equivalent) model: text, topic tag, `generated_at`
- [ ] Celery: generate observation ≤ once / 24h / user; retain prior on failure
- [ ] Settings: Observations enabled / instruction / tone / max length
- [ ] Stress points aggregated from configured multi-select answers in range
- [ ] Tests for empty/sparse states and streak edge cases

### Slice F — Docs & contract freeze
- [ ] Update `docs/API.md` with all new endpoints
- [ ] Update `docs/API_DATABASE_DEEP_DIVE.md` for new models and write paths
- [ ] Mark open questions resolved / deferred in this plan
- [ ] Admin/mobile contract review checklist

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
| (extend) | `/sessions/<id>` | Expose check-in summary + completed_at |
| (extend) | `/sessions/start` | Check-in phase for returning users |

### Onboarding flows

| Method | Path | Notes |
|---|---|---|
| GET | `/onboarding/status` | `onboarded`, `refresh_due`, … |
| GET | `/onboarding/flow` | Server-selected or `?variant=` |
| POST | `/onboarding/answers` | Commit step or full flow → knowledge entries |

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
| 1 | Can admins manually push a knowledge question into a user’s next session? | §1.9 | _TBD_ | |
| 2 | Tell users when AI uses remembered information? | §1.9 | _TBD_ (may be client-only) | |
| 3 | Pre-exercise: every repeat vs first repeat only? | §2.8 | _TBD_ | |
| 4 | Skip pre-exercise if same exercise twice in one day? | §2.8 | _TBD_ | |
| 5 | Companion identity (“Toni”) — Settings vs hardcode? | §3.9 | _TBD_ | |
| 6 | Refresh deferrable (“Remind me later”)? | §3.9 | _TBD_ | |
| 7 | Knowledge field value types (text/number/enum/multi)? | §1.3 | Deferred default: `text` / `number` / `boolean` / `single_choice` / `multiple_choice` (Slice A) | |
| 8 | Dual-write Attribute + Knowledge during transition, or cut over? | — | _TBD_ | |
| 9 | Coexistence strategy for legacy `Question.pre_exercise` form questions | §2 | _TBD_ | |

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

- [ ] This plan reviewed and open questions filled
- [ ] Slice A merged
- [ ] Slice B merged (chat can read/write knowledge)
- [ ] Slice C merged (pre-exercise contracts stable for admin UI)
- [ ] Slice D merged (mobile onboarding can integrate)
- [ ] Slice E merged (Progress tabs can integrate)
- [ ] `docs/API.md` + deep dive updated
- [ ] Staging backfill job run and sampled for compliance
- [ ] Feature flags / settings defaults confirmed (observations on, pre-exercise on)

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
