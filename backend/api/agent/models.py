from __future__ import annotations

from django.db import models

from ..asset.models import Asset
from ..image.models import Image
from ..exercise.models import Exercise

from ..message.models import Message
from ..participant.models import Participant

from ..utils.Models import SmartModel
from ..utils.Fields import CharIDField


class Agent(SmartModel):
    """
    Model instance for storing the AI agent that interacts with a Consumer
    """
    id = CharIDField(primary_key=True, prefix="agt_")

    avatar = models.OneToOneField(Image, related_name="avatar", on_delete=models.DO_NOTHING)

    created_by = models.ForeignKey("api.User", related_name="agents", on_delete=models.CASCADE)

    name = models.CharField(max_length=255)

    default = models.BooleanField(default=False)

    description = models.CharField(max_length=255)

    model = models.CharField(max_length=255, default="gemini-3.1-flash-lite")

    context = models.TextField(null=True)

    consumers_no = models.PositiveIntegerField(default=0)

    def __str__(self):
        """Return a human-readable representation of the model instance."""
        return "Agent: {}".format(self.id)

    @staticmethod
    def get_default() -> Agent | None:
        """
        Retrieves the default agent. If no agent is marked as default,
        it returns the oldest created agent.
        """
        agent = Agent.objects.filter(default=True).first()
        if agent:
            return agent

        agent = Agent.objects.all().order_by("created_at").first()

        return agent

    @staticmethod
    def get_response(session, user_message: Message):
        from ..utils import Constants, Agent as AgentUtils

        consumer = session.consumer

        asset = None
        exercise = None

        if user_message.text == Constants.MESSAGE_TEXT_SKIP_STEP:
            if session.in_pre_exercise_phase():
                response = AgentUtils.ExerciseResponse(
                    is_step_complete=False,
                    text="Cannot skip during pre-exercise check-in",
                    step_no=0,
                    completion_result=None,
                    reasoning="Skip step ignored during pre-exercise check-in",
                    suggested_responses=[],
                )
            else:
                response = AgentUtils.ExerciseResponse(
                    is_step_complete=True,
                    text="Step Auto Skipped",
                    step_no=session.current_step_no,
                    completion_result="Step Skipped",
                    reasoning="Skip step triggered",
                    suggested_responses=[]
                )
            usage = {"_step_skipped": True}
        elif user_message.text in [Constants.MESSAGE_TEXT_ASSET_IMAGE, Constants.MESSAGE_TEXT_ASSET_POST, Constants.MESSAGE_TEXT_ASSET_FILE]:
            assets = Asset.objects.filter()
            if user_message.text == Constants.MESSAGE_TEXT_ASSET_IMAGE:
                assets = assets.filter(image__isnull=False)
            elif user_message.text == Constants.MESSAGE_TEXT_ASSET_POST:
                assets = assets.filter(post__isnull=False)
            if user_message.text == Constants.MESSAGE_TEXT_ASSET_FILE:
                assets = assets.filter(file__isnull=False)

            asset = assets.first()
            text = "Asset Returned" if asset else "No Matching Asset Found"
            if session.exercise:
                response = AgentUtils.ExerciseResponse(
                    is_step_complete=False,
                    text=text,
                    step_no=session.current_step_no,
                    completion_result=None,
                    reasoning=text,
                    suggested_responses=[],
                    asset_id=None
                )
            else:
                response = AgentUtils.GeneralResponse(
                    text=text,
                    reasoning=text,
                    suggested_responses=[],
                    asset_id=None,
                )
            usage = {}
        elif user_message.text in [Constants.MESSAGE_TEXT_EXERCISE]:
            exercise = Exercise.objects.filter(status=Constants.EXERCISE_STATUS_PUBLISHED).first()

            text = "Exercise Returned" if exercise else "No Matching Exercises Found"
            if session.exercise:
                response = AgentUtils.ExerciseResponse(
                    is_step_complete=False,
                    text=text,
                    step_no=session.current_step_no,
                    completion_result=None,
                    reasoning=text,
                    suggested_responses=[],
                    asset_id=None
                )
            else:
                response = AgentUtils.GeneralResponse(
                    text=text,
                    reasoning=text,
                    suggested_responses=[],
                    asset_id=None,
                )
            usage = {}
        else:
            response, usage, asset, exercise = AgentUtils.get_response(consumer_message=user_message, session=session)

        from ..utils.ExerciseOffer import format_agent_offer

        suggested_responses, text = format_agent_offer(response, exercise, session)

        step_no = response.step_no if hasattr(response, "step_no") else None
        completion_result = response.completion_result if hasattr(response, "completion_result") else None
        is_step_complete = response.is_step_complete if hasattr(response, "is_step_complete") else None

        if step_no == 0 and session.exercise_id:
            step_no = 1

        if session.exercise_id and step_no > session.current_step_no and not is_step_complete:
            is_step_complete = True

        if is_step_complete and not completion_result:
            # todo handle this properly
            completion_result = None

        participant = Participant.objects.filter(session=session, agent=consumer.agent).first()
        agent_message = Message.objects.create(
            usage=usage,
            asset=asset,
            step_no=step_no,
            session=session,
            exercise=exercise,
            text=text,
            sender=participant,
            reasoning=response.reasoning,
            is_step_complete=is_step_complete,
            completion_result=completion_result,
            suggested_responses=suggested_responses,
        )

        return agent_message
