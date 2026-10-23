from django.test import override_settings
from unittest.mock import patch

from ...session.models import Session, SessionStep
from ...step.models import Step
from ...utils.Agent import _prepare_prompt, _prompt_phase
from ...utils.extraction import extract_step_result
from ..utils.BaseTest import BaseTest
from ..utils.manager import General


def _replace_steps(exercise):
    exercise.steps.all().delete()
    titles = [
        "Name it",
        "Plan it",
        "Live step",
        "Later one",
        "Later two",
    ]
    created = []
    for index, title in enumerate(titles):
        created.append(
            Step.objects.create(
                exercise=exercise,
                title=title,
                description=f"Description {index + 1}",
                instructions=f"Instructions {index + 1}",
                completion_label=f"Label {index + 1}",
                completion_prompt="Extract the result." if index < 2 else None,
                key=f"step_{index + 1}",
                reference_material=f"Reference {index + 1}",
                done_when=f"Done when {index + 1}",
                order=index,
            )
        )
    exercise.steps_no = 5
    exercise.save(update_fields=["steps_no", "updated_at"])
    return created


@override_settings(AI_STATE_MACHINE_ENABLED=True)
class Wp5StepRenderingTests(BaseTest):
    def endpoint(self):
        return "sessions"

    def test_step_three_shows_results_full_step_and_outlines(self):
        exercise = General.create_exercise()
        steps = _replace_steps(exercise)
        session = Session.objects.create(
            consumer=self.consumer_one,
            exercise=exercise,
            current_step_no=3,
            total_steps_no=5,
            state="step_active",
        )
        SessionStep.create(session, exercise)
        for index in (0, 1):
            row = session.session_steps.get(order=index)
            row.completed = True
            row.completion_result = f"Result {index + 1}"
            row.save(update_fields=["completed", "completion_result", "updated_at"])

        prompt = _prepare_prompt(session)

        self.assertIn("<COMPLETED_STEPS>", prompt)
        self.assertIn("<KEY>step_1</KEY>", prompt)
        self.assertIn("<NAME>Name it</NAME>", prompt)
        self.assertIn("<RESULT>Result 1</RESULT>", prompt)
        self.assertIn("<KEY>step_2</KEY>", prompt)
        self.assertIn("<RESULT>Result 2</RESULT>", prompt)
        self.assertIn("<TITLE>Live step</TITLE>", prompt)
        self.assertIn("<INSTRUCTIONS>Instructions 3</INSTRUCTIONS>", prompt)
        self.assertIn("<REFERENCE>Reference 3</REFERENCE>", prompt)
        self.assertIn("<DONE_WHEN>", prompt)
        self.assertIn("<STEP_OUTLINE>", prompt)
        self.assertIn("<NAME>Later one</NAME>", prompt)
        self.assertIn("<NAME>Later two</NAME>", prompt)
        self.assertNotIn("<TITLE>Name it</TITLE>", prompt)
        self.assertNotIn("<TITLE>Later one</TITLE>", prompt)
        self.assertIn("<REFERENCE>", prompt.split("<SESSION_CONTEXT>", 1)[0])
        self.assertNotIn("weigh evidence for or against a thought or worry", prompt)
        self.assertNotIn("0 to 10 scale", prompt)
        self.assertNotIn("balanced or more accurate thought", prompt)
        self.assertNotIn("brainstorm solutions, plans, or who can support them", prompt)
        self.assertIn("only as background", prompt)
        self.assertIn("ask if you have it right", prompt)
        self.assertNotIn("Do not reframe the situation", prompt)
        self.assertNotIn("cognitive restructuring as appropriate", prompt)
        self.assertEqual(_prompt_phase(session), "step:3:step_active")
        self.assertEqual(steps[2].title, "Live step")

        session.cached_prompt = prompt.replace(
            "ask if you have it right",
            "Do not reframe the situation. ask if you have it right",
        )
        session.save(update_fields=["cached_prompt", "updated_at"])
        rebuilt = _prepare_prompt(session)
        self.assertNotIn("Do not reframe the situation", rebuilt)
        self.assertIn("ask if you have it right", rebuilt)

    def test_live_step_script_includes_title_instructions_and_reference(self):
        from ...utils.Agent import _current_step_instructions

        exercise = General.create_exercise()
        steps = _replace_steps(exercise)
        steps[0].title = "Name the Worry"
        steps[0].instructions = "Ask what they are worried about."
        steps[0].reference_material = "Worry is a behaviour, not a solution."
        steps[0].save(
            update_fields=[
                "title",
                "instructions",
                "reference_material",
                "updated_at",
            ]
        )
        session = Session.objects.create(
            consumer=self.consumer_one,
            exercise=exercise,
            current_step_no=1,
            total_steps_no=5,
            state="step_active",
        )
        SessionStep.create(session, exercise)
        script = _current_step_instructions(session)
        self.assertIn("Name the Worry", script)
        self.assertIn("Ask what they are worried about.", script)
        self.assertIn("Worry is a behaviour, not a solution.", script)

    def test_missing_completion_prompt_does_not_call_the_model(self):
        step = Step(completion_prompt=None)
        with patch("api.utils.AI.AI.ask") as ask:
            self.assertIsNone(extract_step_result(None, step))
        ask.assert_not_called()
