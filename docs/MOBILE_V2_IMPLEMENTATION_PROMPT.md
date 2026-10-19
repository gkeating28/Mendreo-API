# Prompt: Implement Mendreo V2 React Native mobile app surfaces

Copy this document into the React Native mobile app agent (or open this file from the API repo) to implement the remaining consumer checklist items.

## Context

The **Mendreo API** (backend) has already shipped V2 Slices A–F on `main` (merged PR #33 in `gkeating28/Mendreo-API`). Your job is to implement the **React Native consumer app UI + API client wiring** only. Do **not** change the admin portal or invent parallel web-only stacks. Do **not** invent new backend endpoints — consume the contracts below.

Backend reference docs (API repo — may not be mounted in the mobile workspace):

- `docs/API.md` — Sessions, Onboarding, Progress
- `docs/V2_BACKEND_IMPLEMENTATION_PLAN.md` §6 + §12 mobile checklist
- `docs/WEB_V2_IMPLEMENTATION_PROMPT.md` — sibling web handoff (same APIs; different shell)

This prompt is intentionally self-contained so the mobile agent does not need those files.

Auth: **consumer** JWT (`IsConsumerPermission`). All endpoints below are consumer-facing unless noted.

## Goal / acceptance checklist

Complete these three consumer workstreams end-to-end (navigation, empty/sparse states, validation, resume/discard, iOS + Android):

1. **Onboarding / Return / Refresh** — Home icon via status; flow screens; answers commit → Home
2. **Pre-Exercise check-in** — session `phase` + Start handoff via `complete-pre-exercise`
3. **Progress & Insights** — Mood / Exercises / Patterns / Streaks against `/progress/*`

Out of scope for v1 (do not build):

- Admin Knowledge CRUD / Settings screens
- “Remind me later” for Refresh (not deferrable — Home dot launches Refresh)
- Client disclosure that AI used remembered info (deferred; no backend disclosure payload)
- Dual-write to legacy Attributes (V2 answers write Knowledge only)
- Inventing admin “push question into next session”
- New native modules unless the app already depends on them

Preserve existing chat/session/message flows; extend them for check-in phase rather than replacing them.

Follow the mobile app’s existing navigation (React Navigation or equivalent), design system, API client, and state management. Match established RN patterns in this repo — do not invent a parallel visual language or a second networking stack.

---

## Platform notes (React Native)

- Support **iOS and Android** at current app min versions; test both for keyboard, safe areas, and back gestures
- Use existing Safe Area / keyboard-avoiding patterns for flow forms and chat input
- Hardware back (Android) / swipe-back (iOS):
  - **Initial** onboarding: block exit (non-abandonable) — confirm or ignore back
  - **Return/Refresh**: allow dismiss without save
  - **Pre-exercise check-in**: back should leave session as resumable incomplete check-in (do not call complete)
- Prefer existing list/chart primitives already in the app; if adding charts, reuse the current chart library
- Deep links: if the app already supports them, map Refresh/Return entry to the same routes Home uses; otherwise skip
- Offline: fail soft with the app’s existing offline/error toast; do not invent a local Knowledge DB
- Initial step-sync (`complete=false`) may use in-memory + optional existing persistence helpers — do not invent a new offline queue

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
  - Not onboarded → push **Initial** stack (non-abandonable)
  - `refresh_due` → show Refresh dot / badge; tap opens **Refresh** (not deferrable in v1)
  - Onboarded and not due → optional Return entry if product already has a re-check entry point; else allow explicit navigate with `variant=return`
- Fetch status on Home focus (or existing home bootstrap); refresh after completing a flow
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
| `prompt` | Already token-resolved — render as-is |

### Question `response_type` rendering (RN)

| Type | UI | Value submitted |
|---|---|---|
| `text` | `TextInput` (multiline if existing pattern) | string |
| `single_choice` | Pressable chips / radio list from `suggested_responses` | string (must match option) |
| `multiple_choice` | Multi-select; honor `min_selections` / `max_selections` | array or comma-joined string (API accepts either) |
| `slider` | Integer **0–10** control; label from `value_labels[index]` / `anchor_labels` | integer 0–10 |

Use accessible labels, large hit targets, and existing haptic/feedback patterns if the app already uses them.

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
- **Initial:** may step-sync with `complete=false` (partial answers). Completing requires `complete=true` **and** every question answered.
- **Return / Refresh:** must submit `complete=true` with **all** answers in one request. Discarding = leave without calling answers (no server draft).
- Success includes `status` (same as `/onboarding/status`) plus `entries_written`, `entry_ids`.

### Navigation / UX requirements

- Full-screen flow stack with companion “Toni”
- Initial: intercept back; no easy abandon; allow stepwise sync if multi-step UX
- Return/Refresh: header close / gesture dismiss without save
- On complete Initial → reset/navigate per `closing_action` (`enter_mendreo` → main tabs/Home)
- On complete Return/Refresh → `back_to_today` (pop to Home/Today)
- Surface field-level 400 errors (slider bounds, choice membership, multi-select counts)
- Empty `questions` array: calm empty state + exit via closing action (no crash)

---

## 3) Pre-Exercise check-in (session phase)

### When it runs

On `GET /sessions/start` (or the app’s existing start path): for a **returning** user starting an exercise with `pre_exercise_enabled`, the session enters check-in with `current_step_no=0`.

Cadence: **every repeat** (including same-day second runs after a completed session). Resuming an **incomplete** same-day session via existing `get_or_create` does **not** re-trigger check-in.

### Session fields (detail / start payload)

| Field | Values / shape |
|---|---|
| `phase` | `pre_exercise` \| `exercise` \| `completed` \| `general` |
| `pre_exercise.pending` | true while in check-in |
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
  - Show check-in **chat** using existing message send/poll path — **not** Step 1 UI yet
  - Sticky/footer Start CTA using `start_button_label` (safe-area aware; above keyboard when input focused if that matches chat UX)
  - On Start → `POST .../complete-pre-exercise` → then enter normal exercise Step 1 from returned session
- Keep one clear composition for check-in (no floating promo badges on media)
- After handoff: `phase` becomes `exercise`; proceed with existing step/message UX
- App backgrounding mid check-in: resume same session in check-in (do not invent a second check-in)
- Disable “jump to step” shortcuts while `pre_exercise.pending`

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

- Points are **only days with data** — **gaps are not zeros**
- `sparse` when fewer than 2 check-ins; `empty` when none
- When `sparse` / `empty`, show empty/sparse UI; `return_onboarding_cta` may navigate to Return flow
- Slider values 0–10; `value_scaled` is ×10 if chart needs 0–100

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
- Prefer `FlatList` / existing list components for breakdown; reuse icon rendering helpers

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

- If `observations_enabled` is false **or** `observation` is null: hide observation card
- Optional: tapping observation opens chat with `chat_seed` if the app supports seeded chat
- Stress bars from `stress_points` answers in range

### Streaks

```json
{
  "check_in": { "current": 3, "best": 5 },
  "exercise": { "current": 1, "best": 4 },
  "copy": "Consistency matters more than perfection"
}
```

- Ignore `from`/`to` for this endpoint
- Timezone = server `TIME_ZONE` for v1 (no per-user TZ)

### UI requirements

- Progress tab/screen with week range control (default this week); refetch on range change and on screen focus
- Dedicated empty and sparse states (no fake zero-filled charts)
- Pull-to-refresh if Home/Progress already use it
- Streaks as header strip or sub-tab; show provided `copy`
- Field keys: mood → `mood`, stress → `stress_points` (admin-seeded; empty → empty state, not hard crash)
- Keep sections single-purpose; avoid dashboard clutter

---

## 5) Integration map (existing RN surfaces)

| Existing surface | Change |
|---|---|
| Auth bootstrap / Home | Call `/onboarding/status`; wire icon/dot; refresh on focus |
| Onboarding navigator | Prefer V2 `/onboarding/flow` + `/answers` for new users |
| Session start / exercise runner | Branch on `phase === "pre_exercise"`; Start → `complete-pre-exercise` |
| Messages / chat | Unchanged transport; check-in uses same send/poll while pending |
| Progress tab | New or rebuilt screens on `/progress/*` |
| Consumer settings | No new consumer settings for observations/cadence (admin-only) |

---

## 6) Implementation preferences

- Reuse existing API client, auth token storage, query helpers, and navigators
- Type response shapes (TypeScript if the app uses it); fail soft on unexpected nulls
- Prefer optimistic UI only where discard/resume rules allow (Return/Refresh are discardable)
- Ship 2–3 intentional motions for Progress empty→data and check-in→exercise handoff if Reanimated/Motí already used
- Do not bundle admin-only routes or web-only CSS approaches; use RN StyleSheet / existing theme tokens
- Keep bundle impact small — no new heavy chart SDK unless already present

---

## 7) Manual QA script (must pass on iOS and Android)

1. **Fresh user:** status → `initial` → complete slider + multi-select → `onboarded=true` → lands on main tabs (`enter_mendreo`)
2. **Back during Initial:** cannot casually exit; Android back does not abandon without product-approved confirm
3. **Step sync:** Initial `complete=false` mid-flow; final `complete=true` requires all questions
4. **Return:** open `variant=return`, dismiss mid-flow → no answers call / no crash; complete all → `back_to_today`
5. **Refresh:** `refresh_due=true` Home dot opens Refresh; after complete, status clears due
6. **Pre-exercise:** start enabled exercise as returning user → `phase=pre_exercise` → chat → Start → Step 1
7. **Background resume:** leave mid check-in, reopen app → still check-in; after complete, second start same day gets check-in again
8. **Progress empty:** no mood → empty/sparse UI; two mood days → two points, gap day omitted
9. **Patterns:** disabled/null observation → no card; stress answers → bars by count
10. **Streaks:** consecutive mood days increment `check_in.current`; copy visible
11. **Keyboard / safe area:** flow inputs and check-in composer usable with keyboard open; Start CTA not obscured

---

## Definition of done

- All three §12 mobile checklist items are implemented and manually verified:
  - [ ] `/onboarding/status|flow|answers` Initial → Home; Return/Refresh
  - [ ] Session `phase` / `complete-pre-exercise` Start button
  - [ ] Progress tabs against `/progress/*` empty/sparse states
- Verified on **iOS and Android** simulators/devices used by the team
- No backend API changes required (if something is truly missing, document it; don’t silently invent routes)
- PR description lists screens/navigators touched + QA notes
