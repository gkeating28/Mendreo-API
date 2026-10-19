# Prompt: Implement Mendreo V2 admin portal surfaces

Copy this document into the admin app agent (or open this file from the API repo) to implement the remaining admin checklist items.

## Context

The **Mendreo API** (backend) has already shipped V2 Slices A–F on `main` (merged PR #33 in `gkeating28/Mendreo-API`). Your job is to implement the **admin portal UI + API client wiring** only. Do **not** change the mobile app. Do **not** invent new backend endpoints — consume the contracts below.

Backend reference docs (API repo — may not be mounted in the admin workspace):

- `docs/API.md` — Knowledge, Exercises, Settings
- `docs/V2_BACKEND_IMPLEMENTATION_PLAN.md` §6 + §12 admin checklist
- `docs/API_DATABASE_DEEP_DIVE.md` — write paths / models

This prompt is intentionally self-contained so the admin agent does not need those files.

Auth: admin JWT. Enforce role permission resource **`knowledge`** for knowledge screens (view/create/edit/delete as the existing RBAC pattern already does for other resources). Sensitive knowledge values may return `"Restricted"` when the admin lacks **`pii:view`** — never treat that as editable real data.

## Goal / acceptance checklist

Complete these three admin workstreams end-to-end (nav, list, create/edit, validation, empty/error states, permission gating):

1. **Knowledge** — Fields / Questions CRUD + test-extraction + per-user consumer knowledge panel
2. **Exercises — Pre-Exercise tab** — authoring fields + list filter + test prompt
3. **Settings** — refresh cadence + observations keys

Out of scope for v1 (do not build):

- Admin “push this knowledge question into a user’s next session” queue
- Consumer Progress tabs / onboarding flows (mobile)
- Dual-write to legacy Attributes

---

## 1) Knowledge Fields

### APIs

- `GET/POST /knowledge-fields`
- `GET/PATCH/DELETE /knowledge-fields/<id>`

**List filters:** `search_term`, `category`, `active`

### Create body fields

| Field | Notes |
|---|---|
| `key` | Unique stable machine key (immutable after create; edit serializer does not allow changing key) |
| `label` | Admin-facing label |
| `category` | Grouping string for profile panels |
| `value_type` | one of: `text`, `number`, `boolean`, `single_choice`, `multiple_choice` |
| `sensitive` | bool — mask without `pii:view` |
| `active` | bool, default true |

IDs use prefix `knf_`.

### UI requirements

- List with search + category + active filters
- Create / edit / soft-delete (DELETE)
- Show `id` (`knf_…`) and `key` clearly
- Seed-aware: Progress expects field keys `mood` and `stress_points` to exist for consumer Progress; if missing, show a non-blocking admin notice recommending those keys

---

## 2) Knowledge Questions

### APIs

- `GET/POST /knowledge-questions`
- `GET/PATCH/DELETE /knowledge-questions/<id>`
- `POST /knowledge-questions/<id>/test-extraction`  
  body: `{ "sample_reply": "..." }`

**List filters:** `search_term`, `active`, `target_field_id`, `trigger`, `flow`

### Key fields

| Field | Notes |
|---|---|
| `prompt` | Question text |
| `target_field` / `target_field_id` | FK → KnowledgeField |
| `trigger` | `first_session` \| `after_n_sessions` \| `on_exercise_completion` \| `manual_only` |
| `trigger_config` | JSON; for `after_n_sessions` must include integer `n >= 1` |
| `suggested_responses` | string[]; required ≥2 for `single_choice` / `multiple_choice` |
| `extraction_prompt` | Used by test-extraction + AI extraction |
| `flows` | subset of `initial`, `return`, `refresh` |
| `order_by_flow` | object map e.g. `{ "initial": 10, "refresh": 20 }` |
| `response_type` | `text` \| `single_choice` \| `multiple_choice` \| `slider` |
| `value_labels` / slider labels | For `slider`: 11 labels (backend pads); ends/middle typically labeled |
| `min_selections` / `max_selections` | Only valid for `multiple_choice` |
| `order`, `active` | Ordering + enablement |

IDs use prefix `knq_`.

### UI requirements

- Full CRUD form with conditional fields by `response_type` and `trigger`
- Flow multi-select + per-flow order editors
- **Test extraction** panel: textarea for sample reply → call test-extraction → show parsed result (dry-run, no persist)
- Validate client-side to match backend rules (choices ≥2, slider labels, multi-select bounds)

---

## 3) Knowledge Entries + per-user consumer panel

### Global entry APIs (optional secondary screens)

- `GET/POST /knowledge-entries` (filters: `consumer_id`, `field_id`, `source`)
- `GET/DELETE /knowledge-entries/<id>`

Entry `source` values: `onboarding` \| `question` \| `ai` \| `admin`.  
IDs use prefix `kne_`.

### Per-user (primary admin UX — put on Consumer detail)

- `GET /consumers/<id>/knowledge` — profile grouped by category (`?include_inactive=true` optional)
- `PATCH /consumers/<id>/knowledge` — admin edit
  - Accept `{ "field_id": "...", "value": "..." }` **or** `{ "entries": [{ "field_id", "value", "confidence"? }] }`
  - Writes append-only entries with `source=admin`
- `GET /consumers/<id>/knowledge/activity` — chronological feed; filter `?source=`
- `GET /consumers/<id>/knowledge/fields/<field_id>/history` — field history (empty/blocked when sensitive + no `pii:view`)

### UI requirements

- Consumer detail tab: **Knowledge**
  - Category-grouped current values (value, source, confidence, updated_at)
  - Inline edit → PATCH (append history; do not overwrite in place in the UI mental model)
  - Activity feed with source filter
  - Field history drawer
- If value is `"Restricted"`, disable edit and explain missing `pii:view`

---

## 4) Exercises — Pre-Exercise Prompt tab

Extend existing Exercise create/edit (do **not** confuse with legacy `Question.pre_exercise` form questions).

### APIs

- Existing `GET/POST /exercises`, `GET/PATCH/DELETE /exercises/<id>`
- List filter: `?pre_exercise=all|enabled|disabled`
- `POST /exercises/<id>/test-pre-exercise-prompt`  
  body: `{ "consumer_id": "<consumer user id>", "run_dry_run": false }`

### Exercise fields to author

| Field | Notes |
|---|---|
| `pre_exercise_enabled` | bool (new exercises default true in API; existing migrated exercises may be false until authored) |
| `pre_exercise_description` | template text; supports consumer tokens |
| `pre_exercise_instruction` | required when enabled **and** status is published |
| `pre_exercise_goal` | required when enabled **and** status is published |
| `pre_exercise_completion_prompt` | used to summarize check-in |
| `pre_exercise_start_button_label` | CTA label after check-in |

### UI requirements

- Dedicated **Pre-Exercise** tab/section on Exercise form
- List badge/filter for enabled vs disabled
- Surface publish validation errors on Instruction/Goal
- **Test prompt** action: pick a consumer → resolve tokens preview; optional dry-run opening message (`run_dry_run: true`) — must not persist session state
- Preserve existing exercise flows (steps, duplicate, publish)

### Product cadence note (for copy / help text)

Cadence is **every repeat** for returning users (including same-day second runs). Incomplete same-day resume does not re-trigger check-in.

---

## 5) Settings

Use existing Settings screen (`GET/POST /settings`). Add/edit these keys alongside existing ones (`survey_enabled`, prompts, etc.):

| Key | Type | Default / notes |
|---|---|---|
| `refresh_onboarding_cadence_days` | int (≥1) | default **30** — days before Refresh is due |
| `observations_enabled` | bool | default **true** — gates Patterns observation card + Celery generation |
| `observations_instruction` | string | system instruction for observation generation |
| `observations_tone_guide` | string | tone guidance |
| `observations_max_length` | int | default **40** (word budget) |

### UI requirements

- Group: **Onboarding refresh** + **Progress observations**
- Boolean toggles for enabled flags; number input for cadence/max length; textareas for instruction/tone
- Round-trip GET → edit → POST → GET without dropping unrelated settings keys

---

## 6) Permissions / nav

- Add nav items only if the signed-in admin role can access them
- Knowledge screens require `knowledge` permission
- Read-only roles: hide create/edit/delete, allow view where permitted
- Super Admin / Admin / Read Only should already have backend role factory defaults — match whatever the admin app does for other resources (`exercises`, `settings`, etc.)

---

## 7) Implementation preferences

- Follow the admin app’s existing patterns for list pages, forms, API clients, toasts, and role gates — do not invent a new design system
- Prefer typed API client methods mirroring backend paths
- Handle 400 validation payloads field-by-field on forms
- Soft-delete: confirm dialog; list should respect active filters
- No cards-in-hero / marketing layout work — this is an internal admin tool; match current admin UI

---

## 8) Manual QA script (must pass)

1. Create KnowledgeField `mood` (number) and `stress_points` (multiple_choice) if missing
2. Create a KnowledgeQuestion targeting `mood`, `response_type=slider`, flows include `initial`, run test-extraction with a sample reply
3. On a consumer, open Knowledge tab, edit a value, confirm activity shows `source=admin` and history grows
4. With a role lacking `pii:view`, confirm sensitive values show `Restricted` and are not editable
5. Enable Pre-Exercise on an exercise, leave Instruction empty, try publish → blocked; fill Instruction+Goal → publish OK
6. Filter exercises by `pre_exercise=enabled`; run test-pre-exercise-prompt for a consumer
7. Settings: set cadence to 45, disable observations, save, reload — values persist

---

## Definition of done

- All three §12 admin checklist items are implemented and manually verified:
  - [ ] Admin: Knowledge Fields / Questions CRUD + test-extraction
  - [ ] Admin: Exercise Pre-Exercise tab + list filter + test prompt
  - [ ] Admin: Settings cadence + observations keys
- No backend API changes required (if something is truly missing, document it; don’t silently invent routes)
- PR description lists screens touched + QA notes
