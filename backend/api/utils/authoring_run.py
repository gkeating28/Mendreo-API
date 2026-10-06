"""Exercise-builder test runs.

A test run keeps a snapshot of the form (including unsaved edits) and a
flagged session. The consumer's real run, and the saved exercise, stay
as they were.
"""

from __future__ import annotations

import copy

from django.db import transaction

from ..exercise.models import Exercise
from ..question.models import Question
from ..step.models import Step
from . import Constants


# Agent.get_response swallows a model error and returns this sentence.
# A test run should surface that as a failure, the same way a dry run does.
_MODEL_FAILURE_TEXT = (
    "Sorry, I had an issue understanding your message, "
    "can you repeat it or rephrase it for me please?"
)

_STEP_DEFAULTS = {
    "title": "Step",
    "description": "",
    "instructions": "",
    "completion_label": "Done",
    "completion_prompt": "",
    "reference_material": "",
    "done_when": "",
    "average_duration": 300,
    "success_title": "Well Done!",
}

_QUESTION_DEFAULTS = {
    "attribute_key": None,
    "suggested_responses": None,
    "survey": None,
    "anchor_labels": None,
    "value_labels": None,
    "min_selections": None,
    "max_selections": None,
    "pre_exercise": None,
    "can_complete_exercise": False,
    "complete_on_value": None,
    "complete_text": None,
    "key": None,
}


def is_authoring_test(session) -> bool:
    return bool(getattr(session, "authoring_test", False))


def write_authoring_snapshot(source, payload):
    """Copy the form onto a new hidden exercise.

    The payload is the form the admin is looking at. A field it omits
    falls back to the saved exercise. Steps and questions left off the
    payload are not copied. The copy is not a catalogue exercise, and
    check-in is off so the run starts at step 1.
    """
    if payload is None:
        payload = {}
    if not isinstance(payload, dict):
        raise ValueError("Exercise payload must be an object.")

    step_specs = _step_specs(source, payload)
    if not step_specs:
        raise ValueError("Add at least one step before starting a test run.")
    question_specs = _question_specs(source, payload)

    with transaction.atomic():
        snapshot = Exercise.objects.create(**_exercise_attrs(source, payload, step_specs))
        for spec in step_specs:
            tag_ids = spec.pop("tag_ids")
            step = Step.objects.create(exercise=snapshot, **spec)
            if tag_ids:
                step.tags.set(tag_ids)
        for spec in question_specs:
            Question.objects.create(exercise=snapshot, session=None, **spec)
    return snapshot


def start_authoring_test(snapshot, consumer):
    """Open a flagged session on the snapshot, at step 1.

    Creates the session directly. Session.get_or_create would abandon
    this person's paused run on the real exercise.
    """
    from ..participant.models import Participant
    from ..session.models import Session, SessionStep
    from .AIWorkerClient import _run_session_greeting
    from .SessionStateMachine import build_session_state

    step_count = snapshot.steps.count()
    if step_count < 1:
        raise ValueError("Add at least one step before starting a test run.")

    session = Session.objects.create(
        consumer=consumer,
        exercise=snapshot,
        authoring_test=True,
        completed=False,
        abandoned=False,
        current_step_no=1,
        total_steps_no=step_count,
        state=Constants.SESSION_STATE_STEP_ACTIVE,
    )
    SessionStep.create(session, snapshot)
    Participant.create_participants(session)
    opening = _run_session_greeting(session)
    if opening is None:
        raise RuntimeError("no opening message")
    if (opening.text or "") == _MODEL_FAILURE_TEXT:
        raise RuntimeError(opening.reasoning or "model failed")
    session.refresh_from_db()
    return session, opening, build_session_state(session)


def _exercise_attrs(source, payload, step_specs):
    def value(name, default=None):
        return _copy_value(payload, source, name, default)

    last = Exercise.objects.order_by("-order").values_list("order", flat=True).first()
    return {
        "title": value("title", ""),
        "subtitle": value("subtitle", ""),
        "description": value("description", ""),
        "category": value("category", ""),
        "status": value("status", Constants.EXERCISE_STATUS_DRAFT),
        "steps_no": len(step_specs),
        "icon": value("icon", "exercise"),
        "icon_svg": value("icon_svg"),
        "icon_background_color": value("icon_background_color", ""),
        "completions_no": 0,
        "average_duration": sum(spec["average_duration"] or 0 for spec in step_specs),
        "order": last + 1 if last is not None else 1,
        "use_when": value("use_when"),
        "reference_material": value("reference_material"),
        "featured": False,
        "authoring_snapshot": True,
        "framework_label": value("framework_label"),
        "sensitive_fields_allowed": value("sensitive_fields_allowed", []),
        "depth_check": bool(value("depth_check", False)),
        "check_in_enabled": False,
        "check_in_tone": value("check_in_tone"),
        "check_in_instruction": value("check_in_instruction"),
        "check_in_goal": value("check_in_goal"),
        "check_in_summary_prompt": value("check_in_summary_prompt"),
        "check_in_start_button_label": value("check_in_start_button_label", "Start exercise"),
    }


def _step_specs(source, payload):
    items = _listed(payload, "steps")
    saved = {}
    if source is not None:
        saved = {step.id: step for step in source.steps.all()}
    if items is None:
        items = [{"id": step_id} for step_id in saved] if saved else []
        items.sort(key=lambda item: saved[item["id"]].order)

    specs = []
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            raise ValueError("Each step must be an object.")
        origin = saved.get(item.get("id")) if item.get("id") else None
        spec = {
            name: _copy_value(item, origin, name, default)
            for name, default in _STEP_DEFAULTS.items()
        }
        spec["order"] = _copy_value(item, origin, "order", index)
        key = _copy_value(item, origin, "key")
        spec["key"] = None if key == "" else key
        spec["result_field_id"] = _relation_id(item, origin, "result_field")
        spec["tag_ids"] = _tag_ids(item, origin)
        specs.append(spec)
    return specs


def _question_specs(source, payload):
    items = _listed(payload, "questions")
    saved = {}
    if source is not None:
        saved = {
            question.id: question
            for question in source.questions.filter(session__isnull=True)
        }
    if items is None:
        ordered = sorted(saved.values(), key=lambda question: question.order)
        items = [{"id": question.id} for question in ordered]

    specs = []
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            raise ValueError("Each question must be an object.")
        origin = saved.get(item.get("id")) if item.get("id") else None
        spec = {
            "type": _copy_value(item, origin, "type"),
            "title": _copy_value(item, origin, "title"),
            "order": _copy_value(item, origin, "order", index),
        }
        if not spec["type"] or not spec["title"]:
            raise ValueError("Each question needs a type and a title.")
        for name, default in _QUESTION_DEFAULTS.items():
            spec[name] = _copy_value(item, origin, name, default)
        if spec["key"] == "":
            spec["key"] = None
        spec["knowledge_field_id"] = _relation_id(item, origin, "knowledge_field")
        specs.append(spec)
    return specs


def _listed(payload, key):
    """None when the form omitted the list, so the saved rows are copied."""
    if not isinstance(payload, dict) or key not in payload or payload[key] is None:
        return None
    raw = payload[key]
    if not isinstance(raw, list):
        raise ValueError(f"{key.capitalize()} must be a list.")
    return raw


def _copy_value(item, source, name, default=None):
    if isinstance(item, dict) and name in item and item[name] is not None:
        value = item[name]
    elif source is not None and getattr(source, name, None) is not None:
        value = getattr(source, name)
    else:
        value = default
    if isinstance(value, (list, dict)):
        return copy.deepcopy(value)
    return value


def _relation_id(item, source, name):
    if isinstance(item, dict) and name in item and item[name] is not None:
        return _id_of(item[name])
    if source is not None:
        return getattr(source, f"{name}_id", None)
    return None


def _tag_ids(item, source_step):
    if isinstance(item, dict) and "tags" in item and item["tags"] is not None:
        raw = item["tags"]
    elif source_step is not None:
        return list(source_step.tags.values_list("id", flat=True))
    else:
        return []
    if not isinstance(raw, list):
        raise ValueError("Step tags must be a list of ids.")
    return [found for tag in raw if (found := _id_of(tag))]


def _id_of(value):
    if value is None or value == "":
        return None
    if isinstance(value, dict):
        return value.get("id")
    if hasattr(value, "pk"):
        return value.pk
    return value
