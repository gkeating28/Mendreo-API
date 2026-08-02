# Prompt: Implement Mendreo V2 end-user web app surfaces

Copy this document into the consumer/web app agent (or open this file from the API repo) to implement the remaining mobile/web checklist items.

## Context

The **Mendreo API** (backend) has already shipped V2 Slices A–F on `main` (merged PR #33 in `gkeating28/Mendreo-API`). Your job is to implement the **end-user web app UI + API client wiring** only. Do **not** change the admin portal. Do **not** invent new backend endpoints — consume the contracts below.

Backend reference docs (API repo — may not be mounted in the web workspace):

- `docs/API.md` — Sessions, Onboarding, Progress
- `docs/V2_BACKEND_IMPLEMENTATION_PLAN.md` §6 + §12 mobile checklist
- `docs/API_DATABASE_DEEP_DIVE.md` — write paths / models

This prompt is intentionally self-contained so the web agent does not need those files.

Auth: **consumer** JWT (`IsConsumerPermission`). All endpoints below are consumer-facing unless noted.

## Goal / acceptance checklist

Complete these three consumer workstreams end-to-end (routing, empty/sparse states, validation, resume/discard behavior):

1. **Onboarding / Return / Refresh** — Home icon via status; flow UI; answers commit → Home
2. **Pre-Exercise check-in** — session `phase` + Start handoff via `complete-pre-exercise`
3. **Progress & Insights** — Mood / Exercises / Patterns / Streaks against `/progress/*`

Out of scope for v1 (do not build):

- Admin Knowledge CRUD / Settings screens
- “Remind me later” for Refresh (not deferrable — Home dot launches Refresh)
- Client disclosure that AI used remembered info (deferred; no backend disclosure payload)
- Dual-write to legacy Attributes (V2 answers write Knowledge only)
- Inventing admin “push question into next session”

Preserve existing chat/session/message flows; extend them for check-in phase rather than replacing them.

Follow the web app’s existing design system, routing, and API client patterns. Apply product frontend rules already used in this app (brand, motion, layout). Do not invent a parallel visual language.

---

## 1) Onboarding status (Home)

### API

`GET /onboarding/status`

### Response shape

```json
{
  "onboarded": false,
  "refresh_due": false,
  "recommended_variant": "initial",
  "cadence_days": 30,
  "last_completed_at": null,
  "last_completed_variant": null
}
```

| Field | Meaning |
|---|---|
| `onboarded` | Consumer has completed Initial (or legacy onboarded) |
| `refresh_due` | Cadence elapsed since last V2 flow completion (or onboarded with no V2 timestamp) |
| `recommended_variant` | `initial` \| `return` \| `refresh` |
| `cadence_days` | From settings (`refresh_onboarding_cadence_days`, default 30) |

### UI requirements

- On Home / Today: show onboarding entry affordance from status
  - Not onboarded → launch **Initial** (non-abandonable)
  - `refresh_due` → show Refresh dot / badge; tap launches **Refresh** (not deferrable in v1)
  - Onboarded and not due → optional Return entry (if product already has a re-check entry point); otherwise Return can be launched explicitly with `?variant=return`
- Do **not** rely on legacy `GET /onboarding` for V2 flows (keep legacy only if already used elsewhere)

---

## 2) Onboarding flow + answers

### APIs

- `GET /onboarding/flow` — server-selected variant, or `?variant=initial|return|refresh`
- `POST /onboarding/answers`

### Variant rules (server-enforced)

| Consumer state | Allowed |
|---|---|
| Not onboarded | Only `initial` |
| Onboarded | `return` or `refresh` (`initial` rejected) |
| Omit `?variant=` | Server picks via `recommended_variant` |

### Flow response shape (key fields)

```json
{
  "variant": "initial",
  "recommended_variant": "initial",
  "questions": [
    {
      "id": "knq_…",
      "prompt": "Resolved prompt with tokens filled",
      "prompt_template": "Raw template",
      "response_type": "slider",
      "suggested_responses": [],
      "anchor_labels": {},
      "value_labels": ["…", "…"],
      "min_selections": null,
      "max_selections": null,
      "order": 10,
      "target_field": {
        "id": "knf_…",
        "key": "mood",
        "label": "Mood",
        "value_type": "number",
        "sensitive": false
      },
      "prior_value": null
    }
  ],
  "questions_total": 1,
  "closing_action": "enter_mendreo",
  "abandonable": false,
  "companion_name": "Toni"
}
```

| Field | Behavior |
|---|---|
| `abandonable` | `false` for Initial (must finish); `true` for Return/Refresh (discardable — no server draft) |
| `closing_action` | `enter_mendreo` (Initial) or `back_to_today` (Return/Refresh) |
| `companion_name` | `"Toni"` — use in UI; avatar may be hardcoded client-side for launch |
| `prior_value` | Prefill when present (especially Return/Refresh) |
| `prompt` | Already token-resolved (`{{user.first_name}}`, `{{knowledge.*}}`, etc.) — render as-is |

### Question `response_type` rendering

| Type | UI | Value submitted |
|---|---|---|
| `text` | Free text | string |
| `single_choice` | One of `suggested_responses` | string (must match option) |
| `multiple_choice` | Multi-select; honor `min_selections` / `max_selections` | array or comma-joined string (API accepts either; stored comma-joined) |
| `slider` | Integer **0–10**; use `value_labels` (11 slots) / `anchor_labels` for ends/middle | integer 0–10 |

### Answers request

```json
{
  "variant": "initial",
  "complete": false,
  "answers": [
    { "knowledge_question_id": "knq_…", "value": 7 }
  ]
}
```

Notes:

- `question_id` is accepted as an alias of `knowledge_question_id`
- **Initial:** may step-sync with `complete=false` (partial answers for client persistence). Completing requires `complete=true` **and** every question in the variant answered.
- **Return / Refresh:** must submit `complete=true` with **all** answers in one request. Discarding = leave without calling answers (no server draft).
- Success response includes `status` (same shape as `/onboarding/status`) plus `entries_written`, `entry_ids`.

### UI requirements

- Full-screen flow with companion “Toni”
- Initial: block back-out / treat as non-abandonable; allow stepwise sync if UX is multi-step
- Return/Refresh: allow dismiss without save; no “save draft”
- On complete Initial → navigate per `closing_action` (`enter_mendreo` → main app/Home)
- On complete Return/Refresh → `back_to_today`
- Handle 400 validation (slider bounds, choice membership, multi-select counts, missing answers on complete)
- Empty question list: show a calm empty state and exit via `closing_action` path (do not crash)

---

## 3) Pre-Exercise check-in (session phase)

### When it runs

On `GET /sessions/start` (or equivalent start path already used): for a **returning** user starting an exercise with `pre_exercise_enabled`, the session enters check-in with `current_step_no=0`.

Cadence: **every repeat** (including same-day second runs after a completed session). Resuming an **incomplete** same-day session via existing `get_or_create` does **not** re-trigger check-in.

### Session fields (detail / start payload)

| Field | Values / shape |
|---|---|
| `phase` | `pre_exercise` \| `exercise` \| `completed` \| `general` |
| `pre_exercise.pending` | true while in check-in (`current_step_no=0` and not completed check-in) |
| `pre_exercise.occurred` | true after handoff |
| `pre_exercise.summary` | check-in summary text (nullable until complete) |
| `pre_exercise.completed_at` | ISO datetime or null |
| `pre_exercise.start_button_label` | CTA label (default `"Start exercise"`) |

### Handoff API

`POST /sessions/<id>/complete-pre-exercise`

```json
{ "summary": "optional client-provided summary" }
```

- If `summary` omitted, backend may generate from conversation + exercise completion prompt
- Returns updated session detail
- 400 if session is not in pre-exercise phase

### UI requirements

- When `phase === "pre_exercise"` / `pre_exercise.pending`:
  - Show check-in chat UI (existing message send/poll path) — **not** Step 1 yet
  - Prominent Start CTA using `start_button_label`
  - On Start → `POST .../complete-pre-exercise` → then enter normal exercise Step 1 UI from returned session
- Do not show detached badges/overlays on hero media if this surfaces share marketing layouts; keep check-in as one clear composition
- After handoff: `phase` becomes `exercise`; proceed with existing step/message UX
- Resume path: if user returns to an incomplete check-in session, continue check-in (do not invent a second check-in)

---

## 4) Progress & Insights

Consumer-only. Default range = current calendar week (Mon–Sun) in Django `TIME_ZONE`. Pass `?from=&to=` as `YYYY-MM-DD`. Max span ~366 days. Streaks ignore range.

### APIs

| Method | Path | Tab |
|---|---|---|
| GET | `/progress/mood` | Mood |
| GET | `/progress/exercises` | Practice / Exercises |
| GET | `/progress/patterns` | Patterns |
| GET | `/progress/streaks` | Streaks (or shared header) |

### Mood — response highlights

```json
{
  "from": "2026-07-27",
  "to": "2026-08-02",
  "points": [
    { "date": "2026-08-01", "value": 7, "value_scaled": 70, "label": "Alright" }
  ],
  "summary": { "average": 7.0, "delta": 1.2, "check_in_count": 2 },
  "empty": false,
  "sparse": false,
  "return_onboarding_cta": false
}
```

Rules:

- Points are **only days with data** — **gaps are not zeros** (do not invent 0 points for missing days)
- `sparse` when fewer than 2 check-ins; `empty` when none
- When `sparse` / `empty`, show empty/sparse UI; `return_onboarding_cta` may invite Return flow
- Slider values are 0–10; `value_scaled` is ×10 if chart needs 0–100

### Exercises

```json
{
  "from": "…",
  "to": "…",
  "total_completions": 3,
  "heatmap": [{ "date": "…", "completed": true }],
  "breakdown": [
    {
      "exercise_id": "…",
      "title": "…",
      "icon": "…",
      "icon_svg": "…",
      "icon_background_color": "…",
      "completions": 3,
      "last_completed_at": "…"
    }
  ],
  "empty": false
}
```

- Heatmap includes every day in range with boolean `completed`
- Breakdown sorted by completions then title

### Patterns

```json
{
  "from": "…",
  "to": "…",
  "observations_enabled": true,
  "observation": {
    "text": "…",
    "topic_tag": "work anxiety",
    "generated_at": "…",
    "chat_seed": "I'd like to talk about this: …"
  },
  "stress_points": [
    { "category": "Work", "count": 2, "recent_dates": ["2026-08-01"] }
  ]
}
```

- If `observations_enabled` is false **or** `observation` is null: hide observation card (do not show placeholder AI fluff)
- Stress bars from `stress_points` multi-select knowledge answers in range
- Optional: tapping observation starts chat with `chat_seed` (if product supports seeded chat)

### Streaks

```json
{
  "check_in": { "current": 3, "best": 5 },
  "exercise": { "current": 1, "best": 4 },
  "copy": "Consistency matters more than perfection"
}
```

- Ignore `from`/`to` for this endpoint
- Timezone = server `TIME_ZONE` for v1 (do not invent per-user TZ)

### UI requirements

- Progress section with date-range control (default this week); refetch on range change
- Dedicated empty and sparse states (no fake charts filled with zeros)
- Streaks can sit above tabs or as their own strip; use provided `copy`
- Loading / error / retry matching existing app patterns
- Field keys used by backend: mood → `mood`, stress → `stress_points` (admin-seeded; if empty, show empty state, do not error hard)

---

## 5) Integration map (existing surfaces)

| Existing surface | Change |
|---|---|
| Auth / Home | Call `/onboarding/status`; wire icon/dot |
| Onboarding screens | Prefer V2 `/onboarding/flow` + `/answers` over legacy Attribute onboarding for new users |
| Session start / exercise runner | Branch on `phase === "pre_exercise"`; Start → `complete-pre-exercise` |
| Messages | Unchanged transport; check-in uses same send/poll while pending |
| Progress / Insights | New or rebuilt tabs on `/progress/*` |
| Settings (consumer) | No new consumer settings for observations/cadence (admin-only) |

---

## 6) Implementation preferences

- Reuse existing API client, auth headers, query helpers, and navigation shells
- Type the response shapes above; fail soft on unexpected nulls
- Prefer optimistic UI only where discard/resume rules allow (Return/Refresh are discardable — don’t fake server drafts)
- Keep one job per screen/section; avoid dashboard clutter on Progress
- Ship 2–3 intentional motions for Progress empty→data and check-in→exercise handoff if the app is motion-capable
- Do not add admin-only routes to the consumer bundle

---

## 7) Manual QA script (must pass)

1. **Fresh user:** `/onboarding/status` → `recommended_variant=initial` → complete flow with slider + multi-select → `onboarded=true` → lands in app (`enter_mendreo`)
2. **Step sync:** Initial with `complete=false` mid-flow persists answers; final `complete=true` requires all questions
3. **Return:** launch `?variant=return`, abandon mid-flow (no answers call) → no crash; complete with all answers → `back_to_today`
4. **Refresh:** with `refresh_due=true`, Home dot opens Refresh; complete clears due state on next status fetch
5. **Pre-exercise:** start enabled exercise as returning user → `phase=pre_exercise` → chat → Start → `complete-pre-exercise` → Step 1
6. **Same-day resume:** leave mid check-in, reopen → still check-in (not a second trigger); after complete, second start same day gets check-in again
7. **Progress empty:** no mood data → `empty`/`sparse` UI; add 2 mood answers on different days → chart shows 2 points with gap day omitted
8. **Patterns:** with observations disabled or null observation → no card; with stress answers → bars sorted by count
9. **Streaks:** after consecutive mood days, `check_in.current` increments; copy visible

---

## Definition of done

- All three §12 mobile/web checklist items are implemented and manually verified:
  - [ ] `/onboarding/status|flow|answers` Initial → Home; Return/Refresh
  - [ ] Session `phase` / `complete-pre-exercise` Start button
  - [ ] Progress tabs against `/progress/*` empty/sparse states
- No backend API changes required (if something is truly missing, document it; don’t silently invent routes)
- PR description lists screens touched + QA notes
