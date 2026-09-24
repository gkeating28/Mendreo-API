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

            if session.in_pre_exercise_phase():
                if agent_message.exercise_id:
                    agent_message.exercise = None
                    agent_message.save(update_fields=["exercise", "updated_at"])
            else:
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
