from django.db import transaction
from django.db.models import F

from ..exercise.models import Exercise
from ..message.models import Message


def apply_agent_response(user_message: Message, agent_message: Message) -> Message:
    """Update session state after the agent reply is persisted.

    Batches session / step / message updates into a single transaction with
    ``update_fields`` to cut remote DB round-trips on the AI write path.
    """
    session = user_message.session

    with transaction.atomic():
        if session.exercise_id:
            completion_result = agent_message.completion_result
            is_step_complete = agent_message.is_step_complete

            session_step = (
                session.session_steps
                .select_related("step")
                .filter(order=session.current_step_no - 1)
                .first()
            )

            agent_update_fields = []
            session_step_update_fields = []

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

                if session.current_step_no < session.total_steps_no:
                    session.current_step_no += 1
                else:
                    session.completed = True
                    Exercise.all_objects.filter(id=session.exercise_id).update(
                        completions_no=F("completions_no") + 1
                    )

            if agent_message.exercise_id:
                agent_message.exercise = None
                agent_update_fields.append("exercise")

            if agent_update_fields:
                agent_message.save(update_fields=list(dict.fromkeys(agent_update_fields)))

            if session_step and session_step_update_fields:
                session_step.save(
                    update_fields=list(dict.fromkeys(session_step_update_fields))
                )

        session.last_message = agent_message
        session.messages_no += 2
        session.agent_messages_no += 1
        session.consumer_messages_no += 1
        session.save(
            update_fields=[
                "last_message",
                "last_asset",
                "messages_no",
                "agent_messages_no",
                "consumer_messages_no",
                "current_step_no",
                "completed",
                "updated_at",
            ]
        )

    return agent_message
