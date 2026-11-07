# How an exercise is configured

This is the field guide for creating an exercise. It matches the current `Exercise` and `Step` models and the code that reads them during a run.

An exercise is a published script. General chat may offer it. A session then runs an optional check-in, then each step in order. The model sees the live step in full. Every other step is only a title. The app, not the model, marks a step complete and moves on.

Older notes still say `pre_exercise_*` and `completion_criteria`. Those column names are gone. Check-in text is `check_in_*`. “Done when” is `done_when`.

`{{token}}` and `{{token|fallback}}` are filled for the person in the session. An unknown token becomes empty. The same tokens work in the exercise description and reference, the check-in texts, and each step’s description, instructions, done-when, and reference.

## What happens in a run

1. **Offer.** General chat sees published exercises that are not authoring snapshots. Each one is an `<EXERCISE>` with id, title, `use_when` (or the description if `use_when` is blank), whether it is featured, and the knowledge-field keys its steps write.
2. **Start.** A new session copies the exercise’s steps into session steps, in `order`. The first run of that exercise for this person starts at step 1. A later run starts in the check-in when `check_in_enabled` is on.
3. **Check-in.** The model gets the check-in tone, instruction, goal, summary prompt, and start-button label. It must not start step 1. The app moves on when the person taps Start. The summary prompt then reads the check-in transcript. If that prompt is empty, the stored summary is “Pre-exercise check-in completed.”
4. **Each step.** The live step is sent as title, description, instructions, reference, and done-when. Other steps are title and status only. `{{last_run.*}}` tokens can see earlier steps in this run by the step `key`.
5. **Finish a step.** The model may say the work is done. The server checks `done_when` against what the person actually said. On a non-final step, a short yes after a readiness question (“are you ready to continue?”) can complete the step without that check. The completion prompt then extracts a result from the person’s words. If `depth_check` is on and that result is too thin, readiness is held and the next turn is asked to make it more concrete. `completion_label` and `success_title` are copied onto the completed step for the app. They are not part of the model’s script.
6. **Last step.** The session is marked complete and the exercise’s completion count goes up by one.

## Exercise fields

### Catalogue

| Field | What it is for | When it is used |
|---|---|---|
| `title` | Name shown to the person and to the model (`<NAME>`, and the exercise name in the prompt). | Catalogue, session, and the system prompt. |
| `subtitle` | Short line under the title in the client. | API response. Not read by the model. |
| `description` | What the exercise is. Once steps are running, the prompt prefixes it with “Clinical background only. Do not read this to the user” and says it does not authorise a technique the step did not name. | Live prompt. Also the fallback for `use_when` when that is blank. |
| `category` | Free-text label. List can be filtered with `?category=`. | API only. |
| `status` | `draft`, `published`, or `archived`. Only `published` exercises are offered in chat and listed as the catalogue. | Offer and catalogue. A published exercise must have `use_when`. If the check-in is enabled, publish also requires `check_in_instruction` and `check_in_goal`. |
| `order` | Sort position among exercises. | Client lists. |
| `featured` | Marks one exercise as featured. Setting this clears `featured` on every other exercise. | Catalogue `<FEATURED>`. A test-run snapshot is never featured. |
| `icon` | Icon name for the client. | API only. |
| `icon_svg` | SVG markup for that icon. | API only. |
| `icon_background_color` | Colour behind the icon. | API only. |
| `steps_no` | Stored step count. The live “step 2 of 5” uses the number of step rows when that is available, so a stale `steps_no` does not end the run early. | Session setup and prompt. Prefer keeping it equal to the number of steps. |
| `average_duration` | Seconds. On create and update it is rewritten as the sum of the steps’ `average_duration`. | API. Not read by the model. |
| `completions_no` | How many times the exercise has been finished. The server increments it when the last step completes. | API. Do not set this by hand for a new exercise. |
| `framework_label` | Optional label stored on the exercise and returned by the API. | Not read by the chat prompt. |
| `use_when` | When general chat should offer this exercise. Required before publish. | Catalogue `<USE_WHEN>`, and the programming line that says to choose an exercise from each exercise’s `use_when` text. If blank at runtime, `description` is used instead. |

### Check-in (returning users)

The check-in runs only when `check_in_enabled` is true and this person has already completed this exercise once. The same day counts. Resuming an unfinished session does not start a second check-in.

The old `pre_exercise_description`, `pre_exercise_instruction`, `pre_exercise_goal`, and `pre_exercise_completion_prompt` columns are not on the model. Write the `check_in_*` fields.

| Field | What it is for | When it is used |
|---|---|---|
| `check_in_enabled` | Turns the check-in on or off. Default on. | Decides whether a returning user starts in the check-in. |
| `check_in_tone` | Voice for the check-in. Sent in the prompt as `<DESCRIPTION>`. | Check-in system prompt, and the admin “test prompt” dry run. |
| `check_in_instruction` | What Toni should do in the check-in. | Same prompt, as `<INSTRUCTION>`. Required to publish while the check-in is enabled. |
| `check_in_goal` | What “done” means for the check-in. | Same prompt, as `<GOAL>`. Required to publish while the check-in is enabled. |
| `check_in_summary_prompt` | Instructions for a separate model call that writes the check-in summary from the transcript. | When the person taps Start. Empty means the fixed sentence “Pre-exercise check-in completed.” The summary is stored on the session and can be read later as `{{last_run.check_in_summary}}`. The check-in prompt also shows this text, but the live step does not run it. |
| `check_in_start_button_label` | Label on the button that leaves the check-in. Default `Start exercise`. Max 24 characters. | Check-in prompt, and the client button. |

### What the model may know about the person

| Field | What it is for | When it is used |
|---|---|---|
| `reference_material` | Exercise-level reference. Resolved tokens are placed in the exercise prompt as background. | Every turn of the run, including the check-in. |
| `sensitive_fields_allowed` | List of knowledge-field keys. Sensitive knowledge is omitted from the prompt unless its key is in this list. | When the knowledge block is built for a check-in or an exercise turn. General chat never receives sensitive fields. |
| `depth_check` | After the model claims a step is done, run the step’s completion prompt and refuse to move on if the extracted result is below the knowledge confidence setting (default 0.6). | Only when this is true and the live step has a `completion_prompt`. The next turn is told the result is not concrete enough. |

### Authoring copies

These are not part of a normal exercise.

| Field | What it is for |
|---|---|
| `authoring_snapshot` | Hidden copy used by an exercise-builder test run. Excluded from the catalogue and from “has this person done this exercise before?”. |
| `authoring_source` | The real exercise a snapshot was copied from. The snapshot reads that exercise’s summary instead of its own. |

## Step fields

Steps are ordered by `order`, starting at 0. The person and the model see that as step 1, step 2, and so on. The first row is the first step.

| Field | What it is for | When it is used |
|---|---|---|
| `title` | Step name. | Live step `<TITLE>`. Other steps appear as `<NAME>` in the outline only. Also stored on the completed-step block as `<NAME>`. |
| `description` | Short account of the step for the model. | Live step `<DESCRIPTION>` only. Not a script. |
| `instructions` | The script for this step, in the order Toni should follow it. This is the text that says what to ask, what to explain, and when to summarise. | Live step `<INSTRUCTIONS>`. This is the task for the turn. The outline of later steps must not be started. |
| `reference_material` | Extra reference for this step only. | Live step `<REFERENCE>`. |
| `done_when` | Concrete elements that must be present in the person’s own words before the step is done. If the text says the person must confirm a summary, the server also requires a summary message and a later agreement. | Live step `<DONE_WHEN>`, plus a line that tells the model to ask readiness only when that work is done. A separate check reads the step transcript against this text. Empty means that check is skipped and the model’s “done” claim is accepted. A short yes after “are you ready to continue?” on a non-final step does not run this check. |
| `completion_prompt` | Instructions for a separate extraction call: pull the step’s result from what the person said. Assistant-only claims are dropped. | When the step is confirmed, and earlier if `depth_check` is on. Not the live conversation script. Empty means no result is extracted. |
| `completion_label` | Short label stored with the result. | Copied onto the session step and the completion message when the step finishes. Not placed in the prompt. |
| `success_title` | Heading for the completion moment. Default `Well Done!`. | Sent to the client when the step completes. Not placed in the prompt. |
| `key` | Stable id for this step inside one exercise. Unique among steps that are not deleted. | Completed-step block `<KEY>`, and `{{last_run.<key>}}` tokens in later text. Leave blank if nothing needs to refer back to this step. |
| `result_field` | Knowledge field that should store the extracted result. Requires a `completion_prompt`. | After a successful extraction, the value is written as a knowledge entry for that field. The field’s key is also listed on the exercise in the general-chat catalogue. |
| `tags` | Tags used to pick an asset (an image or other media) for this step. A tag whose name is another exercise’s title is ignored. | Only when the model asks to show an asset for the current step. No remaining tags means no asset. |
| `order` | Position in the exercise, from 0. | Session step order, “step N of M”, and which step is live. |
| `average_duration` | Expected seconds for this step. Default 300. | Summed into the exercise’s `average_duration` on save. Not read by the model. |

## What to write in `instructions` and `done_when`

`instructions` is the ordered script. Write it as the sequence Toni should follow: the first question, the next question, then the summary. The live prompt tells the model that this block is the only task, and that the exercise description and the therapeutic text do not authorise a different technique.

`done_when` is the test for finishing, not a second script. Name the concrete things the person must have said. If a summary has to be agreed, say that the person confirmed the summary. The checker ignores a summary that only Toni wrote.

`description` on the step can say what the step is for. It is not a substitute for `instructions`.

## Tokens worth knowing

| Token | Filled from |
|---|---|
| `{{user.first_name}}` and the other `user.*` tokens | The account. |
| `{{exercise.description}}` | This exercise’s description. |
| `{{last_run.check_in_summary}}` | The check-in summary from the previous completed run. |
| `{{last_run.<step key>}}` | That step’s saved result from the previous completed run. |
| `{{form.<question key>}}` | An answer on a question attached to this exercise. |

## Fields the model does not use as its script

`subtitle`, icons, `category`, `order`, `average_duration`, `completions_no`, `framework_label`, `completion_label`, `success_title`, and `featured` are for the client or for bookkeeping. `completion_prompt` is used only by the extraction call. `done_when` is both shown to the model and checked by the server.
