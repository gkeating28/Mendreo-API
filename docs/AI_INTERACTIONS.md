# How Mendreo uses the AI model

This document describes every path that calls a language or image model, and the exact sequence of steps for each. Chat and exercises share one conversational engine. Everything else is a one-shot structured call with no session history.

Related code:

- Conversational turns: `backend/api/utils/Agent.py`, `backend/api/agent/models.py`
- One-shot calls: `backend/api/utils/AI.py`
- Provider selection / failover: `backend/api/utils/AiProviderFactory.py`
- Prompt templates: `backend/api/utils/files/general_prompt.txt`, `backend/api/utils/files/exercise_prompt.txt`
- Defaults: `backend/api/utils/Constants.py` (`PROMPT_*`), admin `Setting` rows

---

## Shared machinery

Two call styles exist. Almost every section below is one or the other.

### A. Conversational agent (`Agent.get_response`)

Used for live chat, exercise greetings, pre-exercise check-in, and exercise steps.

1. Resolve the consumer’s assigned `Agent.model` (default `gemini-3.1-flash-lite`). `Agent.context` is stored on the agent row but is **not** injected into prompts.
2. Build or reuse the session system prompt (`_prepare_prompt` → `session.cached_prompt`).
3. Construct a pydantic-ai `Agent` with:
   - `system_prompt` = cached prompt
   - `output_type` = `GeneralResponse` (no exercise) or `ExerciseResponse` (exercise)
   - tools `get_asset` and `get_exercise` (limit 2 tool calls)
   - `message_history` = `session.cached_history`
4. Run `agent.run_sync(user_prompt=<latest user text>, …)` through `run_with_failover` (default provider, then other enabled Google / OpenAI / Anthropic providers).
5. On success, persist `cached_history` and usage. On failure, return a canned apology; history is not updated.
6. Sanitize `suggested_responses`. Persist an agent `Message`. Apply session/step side effects (`MessageFlow.apply_agent_response`).

The **output schema field descriptions** are extra instructions on every conversational call (how `text` and chips must read; for exercises, when `is_step_complete` may be true and what `completion_result` must contain).

Where the work runs:

| Config | Behaviour |
|---|---|
| `AI_ASYNC_MESSAGES=true` | Enqueue Celery (`process_agent_response` / `process_session_greeting`); client polls for the reply |
| `AI_WORKER_URL` set | HTTP POST to `/internal/ai/message-response` or `/internal/ai/session-greeting` |
| Otherwise | Run in-process |

QA command texts (`qa skip step`, `qa asset image|post|file`, `qa exercise`) skip the model and return a canned agent message.

### B. One-shot structured ask (`AI.ask`)

Used for summaries, observations, extraction tests, pre-exercise dry-runs / completion summaries, and articles.

1. Build a pydantic-ai `Agent` with `output_type` = the requested schema only (no system prompt, no tools, no history).
2. Send the whole instruction as `user_prompt`.
3. Return `result.output` as a dict. Failover is the same as conversational calls.
4. Image generation is separate: Google Imagen via `AI.generate_image` (not pydantic-ai chat).

### System prompt assembly (`_prepare_prompt`)

On the first AI turn of a session (and whenever `cached_prompt` is cleared):

1. If `cached_prompt` is set and still valid, return it. Invalid if it is a general-chat prompt that still says “click the exercise”.
2. Load `general_prompt.txt` when `session.exercise` is null, otherwise `exercise_prompt.txt`.
3. Fill slots:
   - `{therapeutic_instructions}` — admin setting `therapeutic_prompt` (default `PROMPT_THERAPEUTIC_INSTRUCTIONS`: persona, CBT / Unified Protocol)
   - `{programming_instructions}` — hard-coded `PROMPT_PROGRAMMING_INSTRUCTIONS` (length, one question at a time, chips, no diagnosis)
   - `{notes}` — consumer `Summary` detailed notes + observations, plus the current knowledge profile (`get_current_knowledge_summary`)
   - `{user_name}`, `{today_date}`
   - General chat only: `{goals}` (admin `general_prompt`) and `{exercises}` (published catalog, cached 5 minutes)
   - Exercise only: exercise id/name/description, step XML or a pre-exercise placeholder, `{exercise_summary_notes}`, optional `{pre_exercise_block}`
4. Save the rendered string to `session.cached_prompt`.

Cache is cleared when knowledge is written for that consumer, and when pre-exercise check-in hands off to Step 1.

---

## 1. General chat turn

Open conversation with no linked exercise. The model triages and may offer an exercise; it must not run one in this session.

### Start (no model)

1. `GET /sessions/today` reuses today’s incomplete general session, or creates one via `Session.get_or_create(consumer)` (no exercise).
2. `POST /sessions` always creates a fresh general session (`Session.create_general`).
3. Participants (consumer + agent) are created. **No greeting LLM call.**

### Each user message

1. Client `POST /messages` with `session` and `text`. The user `Message` is committed first.
2. If this is a Yes/No chip reply to an exercise offer, see [section 2](#2-exercise-offer-yesno-no-model). Otherwise continue.
3. `Agent.get_response`:
   - Skip LLM for QA commands; else call `AgentUtils.get_response`.
   - First turn: build `general_prompt.txt` (therapeutic + programming + published `<EXERCISES>` + `<CLIENT_SUMMARY>` + `<GOALS>`).
   - `<GOALS>` is the admin `general_prompt` (default: follow-ups first, daily check-in) plus a hardcoded **Triage** block: pick an exercise from `<EXERCISES>`, call `get_exercise`, name it, ask Yes/No, refuse to walk through the exercise in this chat.
   - Output schema: `GeneralResponse` (`text`, `suggested_responses`, `reasoning`, optional `asset_id`).
   - Tool `get_exercise(exercise_id)` may attach a published exercise to the deps.
4. If an exercise was attached, `format_agent_offer` forces Yes/No chips and, if needed, appends “Would you like to start an exercise? Yes or no.”
5. Persist the agent message. `MessageFlow` increments session message counts (`last_message`, `messages_no`, …). No step progression.

Later turns reuse `cached_prompt` and append to `cached_history`. The only new user prompt is the latest message text.

---

## 2. Exercise-offer Yes/No (no model)

When general chat attached an exercise and the client taps a suggestion chip.

1. `POST /messages` with `from_suggested_response=true` and text `Yes` or `No`.
2. `maybe_handle_offer_response` runs **before** the LLM.
3. If there is a pending offer with Yes/No chips:
   - **No** — clear chips, persist a short decline from the agent, no new session.
   - **Yes** — clear chips; the client is expected to start the exercise via `GET /sessions/start?exercise_id=…` (this path does not create the exercise session).
4. Typed text (not a chip tap) always falls through to a normal general-chat turn.

---

## 3. Exercise session greeting

The first assistant line of a **new** exercise run. Resume of an incomplete run does not greet again.

### Decide phase

`GET /sessions/start?exercise_id=…` → `Session.get_or_create`:

1. If an incomplete, non-abandoned run for this exercise exists and `restart` is false, return it (no greeting).
2. If `restart=true`, mark paused runs abandoned and create a new session.
3. Clone exercise questions onto the session; create `SessionStep` rows; create participants.
4. Set `current_step_no`:
   - `0` if `pre_exercise_enabled` **and** the consumer has at least one **completed** session for this exercise (every repeat, including same-day).
   - `1` otherwise (first-ever run, or pre-exercise disabled).

### Greeting call

`request_session_greeting(session)` (skipped if there is no exercise):

1. Build a **synthetic consumer message** (not saved as a user chat row):
   - Pre-exercise: *“Hi, I'd like to practise this exercise again. Please start with the pre-exercise check-in before we begin Step 1.”*
   - Step 1: *“Hi, I'd like to practise this exercise. Can you greet me and explain the exercise please?”*
2. Run the same conversational agent as a normal turn (`ExerciseResponse` schema).
3. Persist only the **agent** message; bump `agent_messages_no` / `messages_no` by 1 (not +2).

The opening line is therefore generated from the system prompt, not a canned string.

---

## 4. Pre-exercise check-in

Returning-user conversational check-in **before** Step 1. `session.current_step_no == 0`.

### Prompt (first AI turn of this phase)

1. `_prepare_prompt` uses `exercise_prompt.txt`.
2. `<STEPS>` is replaced with *“Pre-exercise check-in is active. Do not run exercise steps yet.”*
3. `format_pre_exercise_prompt_block` injects `<PRE_EXERCISE_CHECK_IN>` with token-resolved fields:
   - `pre_exercise_description`
   - `pre_exercise_instruction`
   - `pre_exercise_goal`
   - `pre_exercise_completion_prompt` (shown here; **executed** only at handoff)
   - start button label
   - rules: stay at `step_no=0`, never `is_step_complete`, do not start Step 1, invite the start button when the goal is met
4. Tokens such as `{{user.first_name}}`, `{{exercise.title}}`, `{{last_session.subject}}`, `{{knowledge.<field_key>}}` are filled from the consumer, last completed session, and knowledge entries.

### Each user message during check-in

1. Same conversational loop as [section 5](#5-exercise-step-conversation), with the cached pre-exercise prompt.
2. `MessageFlow` **forces** `step_no=0`, `is_step_complete=false`, and strips `completion_result` even if the model sets them.
3. Check-in ends only via the explicit Start action ([section 6](#6-pre-exercise-handoff-start-exercise)), not via step completion.

---

## 5. Exercise step conversation

Guided run after check-in (or immediately on a first-ever start).

### Prompt (first AI turn of this phase)

1. `_prepare_prompt` uses `exercise_prompt.txt` with extra programming rules: stay on this exercise; `completion_result` must be the user’s own words; ready-gate before advancing.
2. Each step is serialized as:

   ```
   <STEP>
     <TITLE>…</TITLE>
     <DESCRIPTION>…</DESCRIPTION>
     <INSTRUCTIONS>…</INSTRUCTIONS>
     <COMPLETION_CRITERIA>…  (+ “ask ready for next step in a separate message” if not last)</COMPLETION_CRITERIA>
     <COMPLETION_PROMPT>…</COMPLETION_PROMPT>
   </STEP>
   ```

3. Also included: exercise id/name/description, step count, `<EXERCISE_SUMMARY>` notes, client summary + knowledge.
4. `pre_exercise_block` is empty.

All steps are listed at once. The model must keep `step_no` on the live step until work is done, then ask readiness in a **separate** message, then set `is_step_complete` only after the user confirms.

`completion_label` is **not** in the prompt; it is copied onto the message after a real complete.

### Each user message

1. `POST /messages` → conversational agent with `ExerciseResponse` (`text`, chips, `reasoning`, `is_step_complete`, `step_no`, `completion_result`).
2. Tool `get_asset(step_no)` may pick a tagged image/post/file for that step (random among a capped id list).
3. `resolve_step_progress` clamps completion: the previous agent text must have been a next-step readiness ask, and the user must confirm (yes/ok). Completing on the ask turn is rejected.
4. `coerce_completion_result` drops placeholders (`N/A`, `Yes`, facilitator copy) and, if needed, recovers the captured answer from earlier user messages in this step.
5. `MessageFlow.apply_agent_response`:
   - If not complete: clear `completion_result` on the message; optionally set `last_asset`.
   - If complete: stamp `completion_label` / `completion_result` on the `SessionStep`; increment `current_step_no`, or mark the session completed and bump `Exercise.completions_no` on the last step.
   - Detach any `exercise` accidentally attached to the agent message (offers are general-chat only).

---

## 6. Pre-exercise handoff (Start exercise)

Client taps the start button: `POST /sessions/<id>/complete-pre-exercise`.

1. Reject unless `current_step_no == 0`.
2. If the body has no `summary`, `generate_pre_exercise_summary`:
   - If `pre_exercise_completion_prompt` is empty, use `"Pre-exercise check-in completed."` (no LLM).
   - Else one-shot `AI.ask`: completion prompt + full check-in transcript → `{ summary }` (temperature 0.2). On failure, the same fallback string.
3. Stamp `pre_exercise_prompt_summary` and `pre_exercise_completed_at`.
4. Set `current_step_no = 1`. **Clear `cached_prompt`.**
5. Call `request_session_greeting` again with the **Step 1** synthetic text (“greet me and explain the exercise”).
6. The greeting turn rebuilds the system prompt **without** the pre-exercise block and **with** the real step list.

---

## 7. Admin test pre-exercise prompt

Dry-run for authors. No session is created.

1. `POST /exercises/<id>/test-pre-exercise-prompt` with a consumer id.
2. Resolve description / instruction / goal tokens against that user (same token context as live check-in).
3. If dry-run is requested, one-shot `AI.ask` with a short “produce only the opening check-in message” instruction plus the resolved fields (temperature 0.4, schema `{ text }`).
4. Return resolved strings, tokens, and optional `dry_run.opening_message`. Nothing is persisted.

---

## 8. Daily chat summary and session ratings

Background, not a live turn. Celery `update_daily_summaries` at 01:00 fans out `update_chat_summary` per consumer who had sessions yesterday.

`Summary.update` → `Agent.update_summary`:

1. Load yesterday’s sessions and messages for that consumer (`Session.get_with_messages`).
2. For each session:
   - Append a chat log chunk to storage (`consumers/<user_id>/chat_log/<date>/<session_id>.txt`).
   - One-shot `AI.ask` (`build_session_prompt`): Unified Protocol note-taker + this session’s transcript + existing summary/observations → `{ subject, rating, rating_reason, risk_level }`.
   - Write those fields (and aggregated token usage) onto the `Session`.
3. After all sessions, one-shot `AI.ask` (`SUMMARY_RESPONSE_SCHEMA`): previous `detailed` / `observations` / `next_steps` plus the day’s transcripts → updated consumer `Summary`.

This path updates the **consumer** `Summary` used in `{notes}` on later chats. Exercise-scoped `ExerciseSummary.update` uses the same function when called, but the nightly job only loads `Summary` for the consumer. The GET-session-summary view currently does **not** invoke `ExerciseSummary.update` (that call is commented out).

---

## 9. Progress observations

Short second-person card on Progress. Not part of the chat system prompt.

1. Celery `generate_user_observations` at 02:00, if setting `observations_enabled` is true.
2. Fan out `generate_user_observation` for consumers with recent activity.
3. Skip if an observation was generated in the last 24 hours.
4. One-shot `AI.ask` (temperature 0.4):
   - `{observations_instruction}` (admin setting)
   - tone guide + max word length
   - `<KNOWLEDGE>` current profile
   - `<RECENT_TRANSCRIPTS>` last 7 days (truncated)
   - schema `{ text, topic_tag }`
5. Trim to `observations_max_length` words; insert a `UserObservation`. On failure, keep the previous row.

---

## 10. Knowledge extraction dry-run

Admin tool only. Live chat does **not** auto-extract knowledge from replies.

1. `POST /knowledge-questions/<id>/test-extraction` with `sample_reply` (optional override `extraction_prompt`).
2. One-shot `AI.ask` (temperature 0.1): question `extraction_prompt` + sample reply + field value-type hint → `{ value, confidence }`.
3. Return the result; do not write a `KnowledgeEntry`.

`KnowledgeQuestion.prompt` is **onboarding form copy** (`GET /onboarding/flow`), not a chat system prompt. Trigger enums (`first_session`, `after_n_sessions`, `on_exercise_completion`) are stored but not executed by the conversational agent. Writing a real knowledge entry (onboarding answers, admin edit) **does** clear that consumer’s `cached_prompt` so the next chat turn reloads `{notes}`.

---

## 11. Article generation

Admin content pipeline.

1. `POST /ai` with `type=article` and optional `theme`.
2. Insert placeholder `Image` + `Post` (`status=generating`).
3. Enqueue Celery `generate_post`.
4. `Post._generate_article`:
   - `AI.generate_article`: one-shot prompt listing up to 10 published articles (title/subtitle/views/impressions) plus optional theme → `{ title, subtitle, body, image_prompt }`.
   - `Image.generate(image_prompt)` (see [section 12](#12-image-generation)).
5. Update the post to draft with generated title/subtitle/body and banner/thumbnail.

---

## 12. Image generation

Used by article generation (not by chat).

1. `AI.generate_image(prompt, aspect_ratio)` requires an enabled **Google** provider (Imagen). No failover to OpenAI/Anthropic.
2. `client.models.generate_images` with safety filters and `person_generation=allow_adult`.
3. `Image.generate` writes bytes to object storage and returns an `Image` row (`uploaded=True`).

---

## Prompt inventory

| Prompt / instruction | Stored where | Used in |
|---|---|---|
| Therapeutic instructions | Setting `therapeutic_prompt` | Every conversational system prompt |
| Programming instructions | `Constants.PROMPT_PROGRAMMING_INSTRUCTIONS` | Every conversational system prompt |
| Extra exercise programming (ready-gate, completion_result) | `exercise_prompt.txt` | Exercise + pre-exercise system prompts |
| General goals + triage | Setting `general_prompt` + triage block in `general_prompt.txt` | General chat only |
| Published exercise catalog | Built from `Exercise` rows | General chat `<EXERCISES>` |
| Client notes + knowledge | `Summary` + `get_current_knowledge_summary` | Every conversational system prompt |
| Exercise metadata + all step XML | Exercise / Step rows | Exercise system prompt (not during check-in steps list) |
| Step `instructions` / `completion_criteria` / `completion_prompt` | Step rows | Exercise system prompt |
| Pre-exercise description / instruction / goal / completion prompt | Exercise rows | Check-in block; completion prompt also at handoff |
| Output schema descriptions | `GeneralResponse` / `ExerciseResponse` Field() text | Every conversational call |
| Session rating prompt | `build_session_prompt` | Nightly per-session `AI.ask` |
| Daily notes prompt | Inline in `update_summary` | Nightly consumer summary `AI.ask` |
| Observations instruction / tone / max length | Settings | Nightly observation `AI.ask` |
| Knowledge `extraction_prompt` | KnowledgeQuestion | Admin dry-run only |
| Knowledge `prompt` | KnowledgeQuestion | Onboarding UI only (no LLM) |
| Article prompt | `AI.generate_article` | Admin `POST /ai` |
| Image prompt | Model-produced `image_prompt` or caller | Imagen |

---

## Sequence overview

```
General chat
  start → no LLM
  user message → general_prompt.txt → model (± get_exercise) → maybe Yes/No offer
  chip Yes/No → no LLM

New exercise
  start → synthetic user text → exercise_prompt.txt
       returning + enabled → PRE_EXERCISE block, step_no=0
       else → full step list, step_no=1
  → model greeting

Check-in messages → cached pre-exercise prompt; step flags ignored

Start exercise
  → completion_prompt + transcript (AI.ask, unless empty)
  → clear cached_prompt → Step 1 greeting with real steps

Step messages → cached exercise prompt ± get_asset
  → complete only after ready-ask + user yes
```
