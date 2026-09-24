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
        from ..knowledge.followup import FollowupReply, handle_onboarding_followup_reply
        from ..utils import Constants, Agent as AgentUtils

        consumer = session.consumer

        asset = None
        exercise = None
        followup = FollowupReply()

        from django.conf import settings as django_settings

        if (
            user_message.text == Constants.MESSAGE_TEXT_SKIP_STEP
            and session.exercise_id
            and not session.in_pre_exercise_phase()
        ):
            from ..utils.SessionStateMachine import skip_step

            return skip_step(session, user_message)

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
                    completion_result=AgentUtils.SKIP_COMPLETION_RESULT,
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
            followup = handle_onboarding_followup_reply(session, user_message)
            if followup.canned_text:
                response = AgentUtils.GeneralResponse(
                    text=followup.canned_text,
                    reasoning=followup.reasoning or "onboarding_followup",
                    suggested_responses=followup.suggested_responses,
                )
                usage = {"_onboarding_followup": True}
            else:
                response, usage, asset, exercise = AgentUtils.get_response(
                    consumer_message=user_message, session=session
                )

        from ..utils.ExerciseOffer import format_agent_offer, is_yes_no_offer
        from ..utils.StepProgress import (
            last_agent_text_for_session,
            resolve_step_progress,
            session_step_total,
        )
        from ..utils.risk import apply_turn_risk
        from ..utils.turn_hint import (
            last_agent_message,
            normalize_question_kind,
            probe_count_for,
            shape_chips,
        )

        suggested_responses, text = format_agent_offer(response, exercise, session)
        if followup.suggested_responses is not None:
            suggested_responses = list(followup.suggested_responses)

        question_kind = normalize_question_kind(getattr(response, "question_kind", None))
        if (
            getattr(response, "asks_readiness", False)
            and not session.in_pre_exercise_phase()
        ):
            question_kind = Constants.QUESTION_KIND_READINESS
        offer_chips = (
            is_yes_no_offer(suggested_responses)
            and not session.exercise_id
            and exercise is not None
        )
        if not offer_chips:
            suggested_responses = shape_chips(suggested_responses, question_kind)
        suggested_responses_kind = (
            Constants.SUGGESTED_RESPONSES_KIND_OFFER
            if offer_chips
            else Constants.SUGGESTED_RESPONSES_KIND_FREE
        )
        previous_agent = last_agent_message(session)
        probe_count = probe_count_for(previous_agent, question_kind)
        resources = apply_turn_risk(
            session,
            user_message.text or "",
            getattr(response, "risk_level", None),
        )

        participant = Participant.objects.filter(session=session, agent=consumer.agent).first()
        agent_message = Message.objects.create(
            usage=usage,
            asset=asset,
            session=session,
            exercise=exercise,
            text=text,
            sender=participant,
            reasoning=response.reasoning,
            suggested_responses=suggested_responses,
            suggested_responses_kind=suggested_responses_kind,
            question_kind=question_kind,
            probe_count=probe_count,
            resources=resources,
        )

        if session.exercise_id:
            from ..utils.SessionStateMachine import on_model_turn

            on_model_turn(session, agent_message, response)

        if followup.decline_after_agent:
            from ..knowledge.followup import decline_onboarding_followup

            decline_onboarding_followup(session)

        return agent_message
