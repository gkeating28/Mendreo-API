# Knowledge fields and questions

Mendreo keeps a structured picture of you so Toni can remember what you have already shared, and so later visits can ask the right questions. That picture is made of fields, questions, and answers.

This describes the behaviour shipped from the Mendreo V2 plan (April 2026 draft): Personalisation, onboarding, and the knowledge engine.

## Fields

A field is one fact Mendreo wants to keep. Examples are how you are feeling, what tends to stress you, or a preference you want Toni to remember.

Each field has:

- A label people can read, and a stable key the system uses (for example `mood` or `stress_points`).
- A category, so your profile can be grouped (Wellbeing, Preferences, and so on). An empty category shows as General.
- A kind of value: free text, a number, yes/no, one choice, or several choices.
- An on/off switch. A field that is off is left out of the current picture Toni sees.
- An optional privacy mark. Staff who are not allowed to see personal information see “Restricted” instead of the answer. History for that field is hidden from them as well.

## Questions

A question is how Mendreo asks for one field. Each question fills exactly one field.

You answer in one of four ways:

- **Text.** You type a reply.
- **One choice.** You pick a single suggested answer.
- **Several choices.** You pick from the suggested answers. The question can require a minimum and cap you at a maximum.
- **Slider.** You choose a whole number from 0 to 10. The question can label the two ends and each step along the scale.

The wording can include things Mendreo already knows: your first name, an answer you gave earlier, and how many days it has been since you last finished a flow. When a question is shown again, it can also carry the answer you gave last time, so the screen can show what is already on file.

A question can be turned off. Only active questions are asked.

## Answers

Every answer is stored as its own record. A newer answer is added beside the older ones. The answer Mendreo uses is the newest one for that field.

Each record keeps:

- The value.
- When it was written.
- Where it came from: a flow question, an import of older onboarding answers, something Toni inferred, or a staff correction.
- A confidence from 0 to 1. Answers you submit yourself are stored at full confidence. An answer Toni infers carries the confidence of that inference.

A staff correction is a new answer, marked as coming from staff. The previous answer stays in the history.

If a question is removed, the answers that came from that question are removed with it.

## Flows

Flows are the questionnaires you walk through. A question can belong to one, two, or all three. You only see the active questions assigned to the flow you are in.

The app chooses the flow for you:

- You have not finished onboarding: **Initial**.
- You have finished onboarding, and an update is due: **Refresh**.
- You have finished onboarding, and an update is not due: **Return**.

Once you are onboarded, a specific flow can still be opened on purpose (for example to replay the first questionnaire). Before onboarding is finished, only Initial is available.

Questions appear in the order set for that flow. If a question has no order for the flow you are in, it uses its general order. Ties fall back to when the question was created.

### Initial

This is the first questionnaire, before Mendreo treats you as onboarded.

You stay in this flow until it is finished. The app can save your place between questions, so a partially completed Initial flow is kept. When every question has an answer, you are marked onboarded and the flow closes by taking you into Mendreo. The companion named in the flow is Toni.

### Return

This is the questionnaire after you are onboarded, while an update is not yet due.

You can leave before the end. Answers are saved when the full set is submitted together. Leaving early does not keep a draft on the server. Finishing returns you to today.

The wording can refer to answers you already gave, so the questions can acknowledge what Mendreo already knows.

### Refresh

Refresh has the same shape as Return: you can leave early, and answers are saved when the full set is submitted. Finishing returns you to today.

The app recommends Refresh when it is time to update what it knows. The default gap is 30 days after you last finished any flow. That gap is a setting, so it can be changed. If you were onboarded on the older onboarding path and have never finished one of these flows, a refresh is already due.

The home indicator opens Refresh when an update is due. In this version the update starts from that indicator.

Finishing Initial, Return, or Refresh resets the clock used to decide the next refresh.

### A thin first answer

On Initial only, a typed answer that does not really say anything (for example “fine” or “the usual”) can be picked up in your first general chat. Choice chips and slider answers are left as they are.

That check runs in the background after you finish Initial, so submitting the flow does not wait on it. In the first chat, Toni asks whether you want to go into that answer, and you can choose “Let's talk about it” or “Not now”. A clearer answer replaces the thin one as the current value. Toni will try this up to two times. Saying not now, or starting on a real topic of your own, closes that follow-up.

## Triggers

A trigger is a separate setting on each question. It records when that question should be asked in conversation, outside the three flows.

| Trigger | Meaning |
|---|---|
| First session | Ask during your first chat session. |
| After a number of sessions | Ask once you have had the number of sessions set on the question. That number is at least 1. |
| After an exercise | Ask when you finish an exercise. |
| Manual only | Ask only when a flow includes the question. This is the default. |

The trigger is saved with the question. The questions you are asked today come from the flows above. A trigger does not yet start a question in chat on its own, and staff do not place a single question into your next session by hand.

## What Toni does with your answers

At the start of a chat, Toni receives a short summary of your current answers: the label, the value, where it came from, and the confidence. The next chat rebuilds that summary from the newest answer on each active field.

The app does not show you a notice that remembered information was used. Staff can see the source and the confidence when they review your profile.

Two answers also feed Progress, when those fields are set up:

- A mood slider (a field whose key is `mood`, or whose question is about how you are feeling) feeds the mood view.
- A multi-choice field of stress points feeds the patterns view for the dates you select.

A check-in that runs before an exercise is separate from these flows. It can read your answers when it writes its own prompt. It does not replace Initial, Return, or Refresh.
