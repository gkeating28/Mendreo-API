from rest_framework import status
from rest_framework.response import Response

from ..setting.models import Setting
from ..message.models import Message
from ..question.models import Question
from ..question.serializers import QuestionDetailSerializer

from ..utils.Permissions import IsConsumerPermission
from ..utils.Views import SmartAPIView

from ..utils import Api


class Survey(SmartAPIView):
    permission_classes = [IsConsumerPermission]

    def get(self, request):
        consumer = self.get_consumer_from_request()

        tasks = [
            {
                "key": "onboarded",
                "label": "Completed Onboarding",
                "requirement": "Create your journey and activate your account",
                "completed": consumer.onboarded,
            },
            {
                "key": "viewed_post",
                "label": "Consume Content",
                "requirement": "Read an article, watch a video or listen to a podcast",
                "completed": consumer.events.filter(type="view").exists(),
            },
            {
                "key": "started_session",
                "label": "Start Session",
                "requirement": "Start a session or exercise",
                "completed": consumer.sessions.exists(),
            },
            {
                "key": "sent_messages",
                "label": "Chat",
                "requirement": "Send at least 3 messages",
                "completed": Message.objects.filter(session__consumer=consumer,
                                                    sender__consumer=consumer).count() >= 3,
            },
        ]

        completed_tasks = [t for t in tasks if t["completed"]]
        incomplete_tasks = [t for t in tasks if not t["completed"]]

        survey_questions = Question.objects.filter(survey=True).order_by("order")
        questions_data = QuestionDetailSerializer(survey_questions, many=True).data

        attributes_data = consumer.attributes.all().values("question", "value")
        attributes_by_qid = {a["question"]: a for a in attributes_data}
        for q in questions_data:
            q["attribute"] = attributes_by_qid.get(q["id"], None)
            if q["type"] == "boolean":
                q["suggested_responses"] = ["Yes", "No"]

        surveyed = consumer.surveyed

        data = {
            "enabled": Setting.get_survey_enabled(),
            "surveyed": surveyed,
            "completed_tasks": completed_tasks,
            "incomplete_tasks": incomplete_tasks,
            "questions": questions_data,
            "code": Api.SURVEY_CODE,
            "web_app_url": Api.SURVEY_WEB_APP_URL,
            "mobile_app_url": Api.SURVEY_MOBILE_APP_URL,
        }

        return Response(data, status=status.HTTP_200_OK)
