from django.conf import settings
from django.db import transaction
from django.db.models import F

from ..exercise.models import Exercise
from ..message.models import Message
from .StepProgress import session_step_total


def apply_agent_response(user_message: Message, agent_message: Message) -> Message:
    """Update session state after the agent reply is persisted.

    Batches session / step / message updates into a single transaction with
    ``update_fields`` to cut remote DB round-trips on the AI write path.
    """
    session = user_message.session
    # Only the legacy step-advancement branch may persist these. A model call
    # loaded before Start still has current_step_no 0; writing it back puts
    # the session into check-in again.
    persist_step_progress = False

    with transaction.atomic():
        if session.exercise_id:
            agent_update_fields = []
            session_step_update_fields = []

            # Pre-exercise check-in: no step advancement until explicit handoff.
            if session.in_pre_exercise_phase():
                if agent_message.is_step_complete:
                    agent_message.is_step_complete = False
                    agent_update_fields.append("is_step_complete")
                if agent_message.completion_result is not None:
                    agent_message.completion_result = None
                    agent_update_fields.append("completion_result")
                if agent_message.step_no != 0:
                    agent_message.step_no = 0
                    agent_update_fields.append("step_no")
                if agent_message.exercise_id:
                    agent_message.exercise = None
                    agent_update_fields.append("exercise")
                if agent_update_fields:
                    agent_message.save(
                        update_fields=list(dict.fromkeys(agent_update_fields))
                    )
            elif settings.AI_STATE_MACHINE_ENABLED:
                if agent_message.asset_id:
                    session.last_asset_id = agent_message.asset_id
                    session_step = (
                        session.session_steps.filter(order=session.current_step_no - 1).first()
                        if (session.current_step_no or 0) >= 1
                        else None
                    )
                    if session_step:
                        session_step.last_asset_id = agent_message.asset_id
                        session_step.save(update_fields=["last_asset_id", "updated_at"])
                if agent_message.exercise_id:
                    agent_message.exercise = None
                    agent_message.save(update_fields=["exercise", "updated_at"])
            else:
                completion_result = agent_message.completion_result
                is_step_complete = agent_message.is_step_complete

                session_step = (
                    session.session_steps
                    .select_related("step")
                    .filter(order=session.current_step_no - 1)
                    .first()
                )

                if agent_message.asset_id:
                    session.last_asset_id = agent_message.asset_id
                    if session_step:
                        session_step.last_asset_id = agent_message.asset_id
                        session_step_update_fields.append("last_asset_id")

                if not is_step_complete:
                    if agent_message.completion_result is not None:
                        agent_message.completion_result = None
                        agent_update_fields.append("completion_result")
                else:
                    agent_message.step_no = session.current_step_no
                    agent_message.suggested_responses = []
                    agent_update_fields.extend(["step_no", "suggested_responses"])

                    if session_step:
                        completion_label = session_step.step.completion_label
                        agent_message.completion_label = completion_label
                        agent_update_fields.append("completion_label")

                        session_step.completed = True
                        session_step.completion_result = completion_result
                        session_step.completion_label = completion_label
                        session_step_update_fields.extend(
                            ["completed", "completion_result", "completion_label"]
                        )

                    total = session_step_total(session)
                    persist_step_progress = True
                    if total and session.total_steps_no != total:
                        session.total_steps_no = total
                    if session.current_step_no < total:
                        session.current_step_no += 1
                    else:
                        # Last catalogue step is done: advance onto the summary
                        # page (current_step_no = total + 1) instead of closing.
                        session.current_step_no = (session.current_step_no or total) + 1
                        session.mark_completed()
                        Exercise.all_objects.filter(id=session.exercise_id).update(
                            completions_no=F("completions_no") + 1
                        )

                if agent_message.exercise_id:
                    agent_message.exercise = None
                    agent_update_fields.append("exercise")

                if agent_update_fields:
                    agent_message.save(
                        update_fields=list(dict.fromkeys(agent_update_fields))
                    )

                if session_step and session_step_update_fields:
                    session_step.save(
                        update_fields=list(dict.fromkeys(session_step_update_fields))
                    )

        stored_last_at = (
            type(session).objects.filter(pk=session.pk)
            .values_list("last_message__created_at", flat=True)
            .first()
        )
        update_fields = [
            "last_asset",
            "messages_no",
            "agent_messages_no",
            "consumer_messages_no",
            "updated_at",
        ]
        # A check-in reply that finishes after Start must not replace the
        # step 1 greeting or rewind the step number.
        if stored_last_at is None or (
            agent_message.created_at and agent_message.created_at >= stored_last_at
        ):
            session.last_message = agent_message
            update_fields.append("last_message")
        session.messages_no = F("messages_no") + 2
        session.agent_messages_no = F("agent_messages_no") + 1
        session.consumer_messages_no = F("consumer_messages_no") + 1
        if persist_step_progress:
            update_fields.extend(
                ["current_step_no", "total_steps_no", "completed", "completed_at"]
            )
        session.save(update_fields=update_fields)

    return agent_message
