from django.db.models import F

from ..exercise.models import Exercise
from ..message.models import Message


def apply_agent_response(user_message: Message, agent_message: Message) -> Message:
    """Update session state after the agent reply is persisted."""
    session = user_message.session

    if session.exercise_id:
        completion_result = agent_message.completion_result
        is_step_complete = agent_message.is_step_complete

        session_step = session.session_steps.filter(order=session.current_step_no - 1).first()
        if agent_message.asset:
            session.last_asset = agent_message.asset
            if session_step:
                session_step.last_asset = agent_message.asset
                session_step.save()

        if not is_step_complete:
            agent_message.completion_result = None
            agent_message.save(update_fields=["completion_result"])
        else:
            agent_message.step_no = session.current_step_no
            agent_message.suggested_responses = []

            if session_step:
                completion_label = session_step.step.completion_label

                agent_message.completion_label = completion_label

                session_step.completed = True
                session_step.completion_result = completion_result
                session_step.completion_label = completion_label
                session_step.save()

            if session.current_step_no < session.total_steps_no:
                session.current_step_no += 1
            else:
                session.completed = True
                Exercise.all_objects.filter(id=session.exercise_id).update(
                    completions_no=F("completions_no") + 1
                )

            agent_message.save(update_fields=["step_no", "completion_label", "suggested_responses"])

        if agent_message.exercise:
            agent_message.exercise = None
            agent_message.save(update_fields=["exercise"])

    session.last_message = agent_message
    session.messages_no += 2
    session.agent_messages_no += 1
    session.consumer_messages_no += 1
    session.save()

    return agent_message
