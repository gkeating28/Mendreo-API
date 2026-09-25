# How the AI works: standard chat and exercise execution

This document describes how Toni (the consumer-facing agent) currently answers messages in **standard chat** and **exercise sessions**. It focuses on the live conversation path (`POST /messages`), not background jobs such as daily summaries or Progress observations.

Primary code:

- `backend/api/utils/Agent.py` — prompt assembly, pydantic-ai agent, tools
- `backend/api/agent/models.py` — `Agent.get_response` (QA shortcuts + persistence)
- `backend/api/utils/MessageFlow.py` — session / step advancement after the reply
- `backend/api/utils/files/general_prompt.txt` — standard-chat template
- `backend/api/utils/files/exercise_prompt.txt` — exercise template
- `backend/api/utils/Constants.py` — hardcoded programming / therapeutic / goal copy
- `backend/api/setting/models.py` — admin-editable prompts stored in the database

---

## 1. Two conversation modes

Every consumer message belongs to a `Session`. The session type decides which template, output schema, and tools apply.

| Mode | How a session is chosen | Template | Structured output |
|---|---|---|---|
| **Standard chat** | `Session.exercise` is `null`. `GET /sessions/today` reuses today’s open general session; `Session.create_general` starts a fresh one. | `general_prompt.txt` | `GeneralResponse` (`text`, `suggested_responses`, `reasoning`, optional `asset_id`) |
| **Exercise execution** | `Session.exercise` is set (start an exercise, or accept a Yes/No offer from chat). | `exercise_prompt.txt` | `ExerciseResponse` (same fields **plus** `is_step_complete`, `step_no`, `completion_result`) |

The Gemini model name comes from the consumer’s assigned `Agent.model` (database). It is **not** part of the prompt text. `Agent.context` exists on the model but is **not** injected into chat prompts today.

---

## 2. What happens on each user message

```
POST /messages
        │
        ├─ persist consumer Message
        │
        ├─ Yes/No exercise-offer chip?  ──► no LLM; confirm or decline in chat
        │
        └─ Agent.get_response
                │
                ├─ QA command texts ("qa skip step", …) ──► skip LLM
                │
                └─ utils.Agent.get_response
                        │
                        ├─ _prepare_prompt()  → system prompt
                        ├─ pydantic-ai Agent.run_sync(
                        │       user_prompt = this message,
                        │       message_history = session.cached_history,
                        │       tools: get_exercise (chat) / get_asset (exercise),
                        │       max 2 tool calls
                        │   )
                        └─ structured GeneralResponse or ExerciseResponse
        │
        ├─ sanitize suggested_responses
        ├─ (exercise) resolve_step_progress + coerce_completion_result
        ├─ persist agent Message
        └─ apply_agent_response()  → counters, step complete, session.completed
```

Voice uses the same `Agent.get_response` + `apply_agent_response` path (`backend/api/voice/services.py`).

On LLM failure the user sees a canned apology; the real exception is stored in `reasoning`.

---

## 3. How the system prompt is assembled

Every live turn uses **one** system prompt, built in `_prepare_prompt(session)` and then cached on `session.cached_prompt`.

The prompt is **not** a single database field. It is a file template filled with a mix of:

1. **Hardcoded files** (`general_prompt.txt` / `exercise_prompt.txt`)
2. **Hardcoded constants** (`Constants.PROMPT_*`)
3. **Admin settings from the `Setting` table** (`general_prompt`, `therapeutic_prompt`)
4. **Per-user / per-exercise rows** (summary, knowledge, exercise steps, published catalogue)

```
template file
    │
    ├─ {therapeutic_instructions}   ← Setting.therapeutic_prompt  (DB, default = Constants.PROMPT_THERAPEUTIC_INSTRUCTIONS)
    ├─ {programming_instructions}   ← Constants.PROMPT_PROGRAMMING_INSTRUCTIONS  (code only)
    ├─ {goals}                      ← Setting.general_prompt      (DB, default = Constants.PROMPT_GENERAL_GOALS)   [chat only]
    ├─ {exercises}                  ← published Exercise rows     (DB, cached 5 min)                              [chat only]
    ├─ {notes}                      ← Summary + KnowledgeEntry    (DB, per consumer)
    └─ exercise slots               ← Exercise / Step / ExerciseSummary / pre-exercise fields                     [exercise only]
```

Admin edits `general_prompt` and `therapeutic_prompt` via `GET/POST /settings`. Defaults are seeded from `Constants` on first `get_or_create`. Changing a setting updates a 5-minute cache of the setting value; **already-open sessions keep their `cached_prompt` until that cache is cleared** (knowledge writes do this; setting edits do not).

### 3.1 Hardcoded vs database — inventory

| Slot in the template | Source | Editable without a deploy? |
|---|---|---|
| XML skeleton (`<DATA>`, section comments, triage copy in chat, step-progression rules in exercise) | `general_prompt.txt` / `exercise_prompt.txt` | No |
| Programming / product rules (Unified Protocol, length, no diagnoses, suggested chips, who built you, “only therapeutic matters”, …) | `Constants.PROMPT_PROGRAMMING_INSTRUCTIONS` | No |
| Extra exercise-only rules (stay on this exercise, dedicated next-step ask, good/bad progression examples) | `exercise_prompt.txt` | No |
| Extra next-step gate appended to every non-final step’s completion criteria | `_get_formatted_exercise_steps_text` in `Agent.py` | No |
| Therapeutic persona (tone, CBT, vicious cycle, challenge don’t endorse) | `Setting` key `therapeutic_prompt` | Yes (admin settings) |
| Chat goals (follow-ups first, daily check-in, triage heading) | `Setting` key `general_prompt` | Yes (admin settings) |
| Extra triage rules under `<GOALS>` | Hardcoded in `general_prompt.txt` | No |
| Published exercise catalogue (`<EXERCISES>`) | `Exercise` rows with `status=published` | Yes (exercise admin) |
| Exercise title, description, step title/description/instructions/completion_criteria/completion_prompt | `Exercise` + `Step` | Yes (exercise admin) |
| Pre-exercise check-in copy | `Exercise.pre_exercise_*` | Yes (exercise admin) |
| Client notes | `Summary.detailed` / `Summary.observations` | Indirect (nightly summarizer) |
| Structured knowledge | latest `KnowledgeEntry` per active `KnowledgeField` | Yes (knowledge / onboarding) |
| Prior runs of this exercise | `ExerciseSummary.detailed` | Indirect (summarizer) |
| Output-field instructions (`text` must be second person, chips must be answers not questions, when `is_step_complete` may be true) | Pydantic `Field(description=…)` on `GeneralResponse` / `ExerciseResponse` | No |

`PROMPT_PROGRAMMING_INSTRUCTIONS` still contains `{today_date}` and `{user_name}` brace tokens. Those live *inside* the substituted string, so they are **not** filled by `str.format` on the template. The template *does* fill `{user_name}` in `<CLIENT_SUMMARY>` and the chat triage block. `{today_date}` is passed into `format()` but is not referenced by either template file.

The programming text also mentions `<FEEDBACK>` and `<ASSETS>` sections that are **not** present in the templates.

### 3.2 Prompt cache

`session.cached_prompt` is reused on later turns unless:

- The session is general chat **and** the cache still contains the retired phrase `"click the exercise"` (legacy rebuild).
- A knowledge write calls `invalidate_consumer_prompt_cache`.
- Pre-exercise handoff sets `cached_prompt = None` so Step 1 is built with the real step list.

The published-exercise catalogue has its own 5-minute Django cache (`prompt:published_exercises_v1`), invalidated when an `Exercise` is saved.

Conversation turns after the first also send `session.cached_history` (pydantic-ai message list as JSON). That is **dialogue history**, not the system prompt.

---

## 4. Standard chat

### 4.1 Intent

Toni is a Unified Protocol / CBT companion. In general chat she should:

1. Use the client summary and knowledge profile (never invent prior history).
2. Follow the admin **goals** (follow-ups, daily check-in).
3. Triage the anxious experience and, when appropriate, pick a published exercise via the `get_exercise` tool.
4. Name the exercise and ask if they want to start. She must **not** run the exercise inside this chat, and must not tell the user to click UI chrome. Suggested Yes / No chips are attached in code.

### 4.2 System prompt shape

`general_prompt.txt` renders:

```
<DATA>
  <THERAPEUTIC_INSTRUCTIONS>   Setting.therapeutic_prompt
  <PROGRAMMING_INSTRUCTIONS>   Constants.PROMPT_PROGRAMMING_INSTRUCTIONS
  <EXERCISES>                  every published exercise (id, title, subtitle, description)
  <CLIENT_SUMMARY>             Summary notes + structured knowledge
  <GOALS>
      Setting.general_prompt
      <Triage>                 hardcoded: categorize → get_exercise → Yes/No, refuse in-chat delivery
  </GOALS>
</DATA>
```

Default `Setting.general_prompt` (`Constants.PROMPT_GENERAL_GOALS`) is only three bullets: follow-ups first, daily check-in, “Triage the Experience”. The detailed triage procedure is the hardcoded `<Triage>` block in the file, not the database field.

### 4.3 Tools and exercise offers

The only tool registered in chat that matters is **`get_exercise(exercise_id)`**. It loads a published `Exercise` and stores it on `deps.matched_exercise`.

After the model returns:

1. `format_agent_offer` forces suggested replies to `["Yes", "No"]` and, if the model did not already invite a start, appends: *“There's an exercise that fits… Would you like to start an exercise? Yes or no.”*
2. That agent message is saved with `exercise` set (the offer card).
3. If the user **taps** Yes or No (`from_suggested_response=true`), `maybe_handle_offer_response` **skips the LLM**:
   - **Yes** — persist the user message only; the client is expected to start an exercise session separately.
   - **No** — a hardcoded decline: *“Okay — I'll leave {title} here until you want it…”*
4. Typed text (not a chip tap) still goes through the LLM.

`get_asset` is registered for both modes but returns `invalid_session` when `session.exercise` is missing.

### 4.4 What is *not* used in live chat

Knowledge **questions** (`KnowledgeQuestion.prompt`, `extraction_prompt`) drive onboarding / admin extraction, not Toni’s chat loop. Their *answers* become `KnowledgeEntry` rows, which **are** injected into `{notes}` on the next uncached prompt.

Progress **observations** (`Setting.observations_*`) are a separate daily generator, not part of `get_response`.

---

## 5. Exercise execution

### 5.1 Session lifecycle

`Session.get_or_create(consumer, exercise)`:

1. Resume an incomplete, non-abandoned run of that exercise if one exists (unless `force_new`).
2. Otherwise create a new session, copy steps into `SessionStep` rows, and copy exercise `Question` rows onto the session.
3. If the user has **already completed this exercise** and `exercise.pre_exercise_enabled`, start in **pre-exercise** (`current_step_no = 0`). Otherwise start at Step 1.
4. Fire a **greeting** turn (`request_session_greeting`) with a **hardcoded fake user message** that is not shown as a consumer bubble:
   - Pre-exercise: *“Hi, I'd like to practise this exercise again. Please start with the pre-exercise check-in before we begin Step 1.”*
   - Otherwise: *“Hi, I'd like to practise this exercise. Can you greet me and explain the exercise please?”*

That greeting is a full LLM turn using the exercise system prompt.

### 5.2 Pre-exercise check-in

While `current_step_no == 0`, the exercise template injects `format_pre_exercise_prompt_block()` instead of real steps. `{exercise_steps}` is replaced with *“Pre-exercise check-in is active. Do not run exercise steps yet.”*

The XML block is built from **database** exercise fields, with `{{token}}` placeholders resolved against the user, last completed session, and knowledge:

| Field | Role |
|---|---|
| `pre_exercise_description` | What this check-in is |
| `pre_exercise_instruction` | How Toni should conduct it |
| `pre_exercise_goal` | When the check-in is done |
| `pre_exercise_completion_prompt` | Used later to summarize the transcript (not for live step completion) |
| `pre_exercise_start_button_label` | Client start button copy |

Hardcoded rules in that block: keep `step_no` at 0, never `is_step_complete`, do not start Step 1, invite the start button when the goal is met.

`apply_agent_response` **strips** any step-complete / completion_result / non-zero `step_no` / attached exercise the model might still emit during check-in.

Handoff is `POST /sessions/<id>/complete-pre-exercise`: stamp summary (LLM over the check-in transcript using `pre_exercise_completion_prompt`, or a fallback sentence), set `current_step_no = 1`, clear `cached_prompt`, greet again for Step 1.

### 5.3 Running steps

Once past check-in, `_get_formatted_exercise_steps_text` renders every `Step` with `Constants.PROMPT_STEP`:

```
<STEP>
  <TITLE>                 step.title
  <DESCRIPTION>           step.description
  <INSTRUCTIONS>          step.instructions
  <COMPLETION_CRITERIA>   step.completion_criteria
                          + hardcoded “ask ready for next step on a separate turn”
                            (omitted on the last step)
  <COMPLETION_PROMPT>     step.completion_prompt
</STEP>
```

Those five step fields are **database content authored in exercise admin**. The extra next-step gate is **hardcoded** so the model cannot treat “move on” inside instructions as permission to complete the step.

Also in the system prompt:

- Exercise id / name / description
- `{pre_exercise_block}` empty after handoff
- Client summary + knowledge (`{notes}`)
- `{exercise_summary_notes}` from `ExerciseSummary` (prior runs of this exercise)

Programming instructions from the file then **override** chat behaviour: stay on this exercise only; `completion_result` must be the user’s own words for what `COMPLETION_PROMPT` asked; never complete in the same turn as the readiness ask; user-initiated “let’s move on” is not enough.

### 5.4 Structured fields and server-side guards

The model returns:

- `text` — spoken to the user (schema: second person, no facilitator notes)
- `suggested_responses` — up to three tap-to-send **answers** in the user’s voice (sanitized in code so they are not restated questions)
- `step_no` — 1-based live step; the server **does not** let the model jump ahead
- `is_step_complete` — true only after the step’s work is done **and** (for non-final steps) the user confirmed a dedicated next-step ask
- `completion_result` — the captured answer; required when complete

Two **hardcoded** post-processors sit between the model and the database:

1. **`resolve_step_progress`** (`StepProgress.py`) — regex gate. Completing a non-final step is allowed only if the *previous* agent message asked a next-step readiness question *and* this user message is a short confirmation (`yes` / `ok` / `ready` / …). Completing in the same turn as a new readiness ask is rejected. Model-incremented `step_no` is ignored; the session stays on `current_step_no` until complete.
2. **`coerce_completion_result`** — if the model marks complete but returns `N/A`, `Yes`, “the user has…”, etc., recover a real quote from recent consumer messages in this step (`completion.py`). `"Step Skipped"` is kept for the QA skip command.

Then `apply_agent_response`:

- Incomplete turn: drop any `completion_result`; optionally attach an asset to the session / session step.
- Complete turn: stamp `SessionStep.completed` + `completion_result` + `completion_label` (from the `Step` row); clear suggested chips; if more steps remain, `current_step_no += 1`; if this was the last step, `session.mark_completed()` and increment `Exercise.completions_no`.

The **`get_asset(step_no)`** tool picks a random `Asset` whose tags overlap the current step’s tags (or any asset if the step has no tags).

### 5.5 Skip / QA commands

These user texts bypass the LLM (`Agent.get_response` in `agent/models.py`):

| Text | Effect |
|---|---|
| `qa skip step` | Force step complete with `completion_result = "Step Skipped"` (ignored during pre-exercise) |
| `qa asset image/post/file` | Attach the first matching asset |
| `qa exercise` | Attach the first published exercise (chat-oriented) |

---

## 6. End-to-end picture

```
                    ┌─────────────────────────────────────────┐
                    │           Setting (admin)               │
                    │  therapeutic_prompt, general_prompt     │
                    └──────────────────┬──────────────────────┘
                                       │
 Constants + template files ───────────┤
 Exercise / Step / knowledge / summary ┤
                                       ▼
                            _prepare_prompt()
                                       │
                    session.cached_prompt (per session)
                                       │
              ┌────────────────────────┴────────────────────────┐
              │                                                 │
     Standard chat                                      Exercise session
     GeneralResponse                                    ExerciseResponse
     tool: get_exercise                                 tool: get_asset
     offer Yes/No in chat                               steps + completion_result
              │                                                 │
              └────────────────────────┬────────────────────────┘
                                       ▼
                            persist Message + apply_agent_response
```

**Practical rule of thumb**

- Change **how Toni talks** (persona, CBT stance) → `Setting.therapeutic_prompt`.
- Change **what general chat tries to do first** (check-in / follow-ups) → `Setting.general_prompt`.
- Change **a specific exercise’s script** → `Exercise` / `Step` fields (and pre-exercise fields for returning-user check-in).
- Change **hard rails** (never run the exercise in chat, next-step confirmation protocol, chip format, length, no diagnoses) → code: template files, `Constants.PROMPT_PROGRAMMING_INSTRUCTIONS`, Pydantic field descriptions, `StepProgress` / `completion` helpers.
