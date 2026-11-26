from types import SimpleNamespace

from rest_framework import status

from ..utils.BaseTest import BaseTest
from ...exercise.models import Exercise
from ...step.models import Step
from ...step.serializers import StepEditSerializer
from ...utils import Constants
from ...utils.authoring import completion_prompt_error, progression_error


OLD_INSTRUCTIONS = "Give feedback, and ask if they are ready to move on."
OLD_PROMPT = "Complete your instructions and move on when the user tells you they're ready."
ONCE_PROMPT = "Once the user has named the thought, ask if they want to stop."


def _messages():
    return (
        progression_error(OLD_INSTRUCTIONS),
        completion_prompt_error(OLD_PROMPT),
    )


def _step(title, instructions, completion_prompt):
    return {
        "title": title,
        "description": "What this step is for.",
        "instructions": instructions,
        "completion_label": "Done",
        "completion_prompt": completion_prompt,
        "average_duration": 300,
        "success_title": "Well Done!",
    }


def _exercise(**overrides):
    data = {
        "title": "Think Flexibly",
        "subtitle": "Challenge unwanted thoughts",
        "description": "Put one unwanted thought into words.",
        "category": "Thinking",
        "icon": "leaf",
        "icon_background_color": "tan",
        "status": Constants.EXERCISE_STATUS_PUBLISHED,
        "use_when": "When a difficult thought is circling.",
        "check_in_enabled": False,
        "questions": [],
        "steps": [
            _step("Name the thought", "Ask for a single thought.", "Quote the user's target thought."),
            _step(
                "Understanding our biases",
                "Ask whether the thought could be a thinking trap.",
                "State the trap the user named.",
            ),
        ],
    }
    data.update(overrides)
    return data


def _saved_step(step, **overrides):
    body = {
        "id": step["id"],
        "title": step["title"],
        "description": step["description"],
        "instructions": step["instructions"],
        "completion_label": step["completion_label"],
        "completion_prompt": step.get("completion_prompt") or "",
        "average_duration": step.get("average_duration") or 300,
        "success_title": step.get("success_title") or "Well Done!",
    }
    body.update(overrides)
    return body


class DraftStepWordingTests(BaseTest):
    def endpoint(self):
        return "exercises"

    def _old_wording(self, steps):
        return [
            _saved_step(steps[0]),
            _saved_step(
                steps[1],
                instructions=OLD_INSTRUCTIONS,
                completion_prompt=OLD_PROMPT,
            ),
        ]

    def test_draft_save_allows_old_wording(self):
        created = self._create(_exercise(), self.admin_one_access_token)
        self.assertEqual(created.status_code, status.HTTP_201_CREATED, created.json)

        response = self._update(
            SimpleNamespace(id=created.json["id"]),
            {
                "status": Constants.EXERCISE_STATUS_DRAFT,
                "steps": self._old_wording(created.json["steps"]),
            },
            self.admin_one_access_token,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json)
        self.assertEqual(response.json["status"], Constants.EXERCISE_STATUS_DRAFT)
        self.assertEqual(response.json["steps"][1]["instructions"], OLD_INSTRUCTIONS)
        self.assertEqual(response.json["steps"][1]["completion_prompt"], OLD_PROMPT)

        archived = self._create(
            _exercise(
                title="Archived wording",
                status=Constants.EXERCISE_STATUS_ARCHIVED,
                steps=[
                    _step("Name the thought", "Ask for a single thought.", "Quote the user's target thought."),
                    _step("Understanding our biases", OLD_INSTRUCTIONS, OLD_PROMPT),
                ],
            ),
            self.admin_one_access_token,
        )
        self.assertEqual(archived.status_code, status.HTTP_201_CREATED, archived.json)
        self.assertEqual(archived.json["status"], Constants.EXERCISE_STATUS_ARCHIVED)

    def test_publish_save_rejects_old_wording(self):
        instruction_message, prompt_message = _messages()
        created = self._create(
            _exercise(status=Constants.EXERCISE_STATUS_DRAFT),
            self.admin_one_access_token,
        )
        self.assertEqual(created.status_code, status.HTTP_201_CREATED, created.json)

        response = self._update(
            SimpleNamespace(id=created.json["id"]),
            {
                "status": Constants.EXERCISE_STATUS_PUBLISHED,
                "steps": self._old_wording(created.json["steps"]),
            },
            self.admin_one_access_token,
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.json)
        self.assertEqual(response.json["steps"][0], {})
        self.assertEqual(response.json["steps"][1]["instructions"], [instruction_message])
        self.assertEqual(response.json["steps"][1]["completion_prompt"], [prompt_message])

        direct = self._create(
            _exercise(
                title="Publish wording",
                steps=[
                    _step("Name the thought", "Ask for a single thought.", "Quote the user's target thought."),
                    _step("Understanding our biases", OLD_INSTRUCTIONS, OLD_PROMPT),
                ],
            ),
            self.admin_one_access_token,
        )
        self.assertEqual(direct.status_code, status.HTTP_400_BAD_REQUEST, direct.json)
        self.assertEqual(direct.json["steps"][1]["instructions"], [instruction_message])
        self.assertEqual(direct.json["steps"][1]["completion_prompt"], [prompt_message])

    def test_blank_use_when_is_rejected_on_publish_only(self):
        published = self._create(
            _exercise(use_when=""),
            self.admin_one_access_token,
        )
        self.assertEqual(published.status_code, status.HTTP_400_BAD_REQUEST, published.json)
        self.assertEqual(
            published.json["use_when"],
            ["A published exercise needs use_when."],
        )

        draft = self._create(
            _exercise(title="Draft without use when", status=Constants.EXERCISE_STATUS_DRAFT, use_when=""),
            self.admin_one_access_token,
        )
        self.assertEqual(draft.status_code, status.HTTP_201_CREATED, draft.json)
        self.assertEqual(draft.json["status"], Constants.EXERCISE_STATUS_DRAFT)

    def test_standalone_step_save_follows_the_exercise_status(self):
        instruction_message, prompt_message = _messages()
        created = self._create(
            _exercise(status=Constants.EXERCISE_STATUS_DRAFT),
            self.admin_one_access_token,
        )
        self.assertEqual(created.status_code, status.HTTP_201_CREATED, created.json)
        step_id = created.json["steps"][1]["id"]

        draft_step = Step.objects.select_related("exercise").get(id=step_id)
        draft_edit = StepEditSerializer(
            instance=draft_step,
            data={"instructions": OLD_INSTRUCTIONS, "completion_prompt": OLD_PROMPT},
            partial=True,
        )
        self.assertTrue(draft_edit.is_valid(), draft_edit.errors)

        Exercise.objects.filter(id=created.json["id"]).update(
            status=Constants.EXERCISE_STATUS_PUBLISHED
        )
        published_step = Step.objects.select_related("exercise").get(id=step_id)
        published_edit = StepEditSerializer(
            instance=published_step,
            data={"instructions": OLD_INSTRUCTIONS, "completion_prompt": OLD_PROMPT},
            partial=True,
        )
        self.assertFalse(published_edit.is_valid())
        self.assertEqual(published_edit.errors["instructions"], [instruction_message])
        self.assertEqual(published_edit.errors["completion_prompt"], [prompt_message])

    def test_publish_without_steps_checks_stored_wording(self):
        instruction_message, prompt_message = _messages()
        once_message = completion_prompt_error(ONCE_PROMPT)
        bad_steps = [
            _step(
                "Name the thought",
                "Ask for a single thought.",
                ONCE_PROMPT,
            ),
            _step(
                "Understanding our biases",
                OLD_INSTRUCTIONS,
                OLD_PROMPT,
            ),
        ]
        for stored_status, title in (
            (Constants.EXERCISE_STATUS_DRAFT, "Draft stored wording"),
            (Constants.EXERCISE_STATUS_ARCHIVED, "Archived stored wording"),
        ):
            created = self._create(
                _exercise(title=title, status=stored_status, steps=bad_steps),
                self.admin_one_access_token,
            )
            self.assertEqual(
                created.status_code, status.HTTP_201_CREATED, created.json
            )

            response = self._update(
                SimpleNamespace(id=created.json["id"]),
                {"status": Constants.EXERCISE_STATUS_PUBLISHED},
                self.admin_one_access_token,
            )
            self.assertEqual(
                response.status_code,
                status.HTTP_400_BAD_REQUEST,
                response.json,
            )
            self.assertEqual(
                response.json["steps"][0],
                {"completion_prompt": [once_message]},
            )
            instructions = response.json["steps"][1]["instructions"]
            prompt = response.json["steps"][1]["completion_prompt"]
            self.assertEqual(instructions, [instruction_message])
            self.assertEqual(prompt, [prompt_message])
            self.assertEqual(
                Exercise.objects.get(id=created.json["id"]).status,
                stored_status,
            )

    def test_client_supplied_exercise_status_is_ignored(self):
        instruction_message, prompt_message = _messages()
        created = self._create(
            _exercise(status=Constants.EXERCISE_STATUS_DRAFT),
            self.admin_one_access_token,
        )
        self.assertEqual(
            created.status_code, status.HTTP_201_CREATED, created.json
        )

        steps = self._old_wording(created.json["steps"])
        for step in steps:
            step["_exercise_status"] = Constants.EXERCISE_STATUS_DRAFT

        published = self._update(
            SimpleNamespace(id=created.json["id"]),
            {
                "status": Constants.EXERCISE_STATUS_PUBLISHED,
                "_exercise_status": Constants.EXERCISE_STATUS_DRAFT,
                "steps": steps,
            },
            self.admin_one_access_token,
        )
        self.assertEqual(
            published.status_code,
            status.HTTP_400_BAD_REQUEST,
            published.json,
        )
        self.assertEqual(published.json["steps"][0], {})
        published_steps = published.json["steps"][1]
        self.assertEqual(
            published_steps["instructions"], [instruction_message]
        )
        self.assertEqual(
            published_steps["completion_prompt"], [prompt_message]
        )
        self.assertEqual(
            Exercise.objects.get(id=created.json["id"]).status,
            Constants.EXERCISE_STATUS_DRAFT,
        )

        drafted = self._update(
            SimpleNamespace(id=created.json["id"]),
            {
                "status": Constants.EXERCISE_STATUS_DRAFT,
                "steps": [
                    {
                        **step,
                        "_exercise_status": (
                            Constants.EXERCISE_STATUS_PUBLISHED
                        ),
                    }
                    for step in self._old_wording(created.json["steps"])
                ],
            },
            self.admin_one_access_token,
        )
        self.assertEqual(
            drafted.status_code, status.HTTP_200_OK, drafted.json
        )
        self.assertEqual(
            drafted.json["status"], Constants.EXERCISE_STATUS_DRAFT
        )
        self.assertEqual(
            drafted.json["steps"][1]["instructions"], OLD_INSTRUCTIONS
        )
        stored_key = Step.objects.filter(
            exercise_id=created.json["id"],
            key="_exercise_status",
        )
        self.assertFalse(stored_key.exists())
