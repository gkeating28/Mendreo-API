from __future__ import annotations

from django.contrib.postgres.fields import ArrayField

from django.db import models

from ..exercise.models import Exercise

from ..utils.Models import SmartModel
from ..utils.Fields import CharIDField, EnumField

from ..utils import Constants


class Question(SmartModel):
    """
    Model instance for questions the platform adin can create
    """
    id = CharIDField(primary_key=True, prefix="qstn_")

    exercise = models.ForeignKey(Exercise, related_name="questions", null=True, on_delete=models.CASCADE)
    
    session = models.ForeignKey("api.Session", related_name="questions", null=True, on_delete=models.CASCADE)

    type = EnumField(options=Constants.QUESTION_TYPES)

    attribute_key = models.CharField(max_length=255, null=True)

    title = models.TextField()

    suggested_responses = ArrayField(models.CharField(max_length=255, blank=False), blank=True, null=True)

    order = models.PositiveIntegerField(default=0)

    survey = models.BooleanField(null=True)

    pre_exercise = models.BooleanField(null=True)

    can_complete_exercise = models.BooleanField(default=False)
    complete_on_value = models.CharField(max_length=255, null=True)
    complete_text = models.CharField(max_length=255, null=True)

    def __str__(self):
        """Return a human-readable representation of the model instance."""
        return "Question: {}".format(self.id)

    def get_permission_key(self):
        """Return the permission key for role-based access control"""
        return "questions"

    @staticmethod
    def get_with_attributes(queryset, consumer, serializer=None):
        from .serializers import QuestionDetailSerializer
        from ..attribute.serializers import AttributeListSerializer

        if not serializer:
            serializer = QuestionDetailSerializer

        questions = queryset.order_by("order")
        questions_data = serializer(questions, many=True).data

        question_ids = []
        for question_data in questions_data:
            question_ids.append(question_data["id"])

        question_ids = list(questions.values_list("id", flat=True))

        attributes = consumer.attributes.filter(question_id__in=question_ids)
        attributes_data = AttributeListSerializer(attributes, many=True).data

        attributes_by_question_id_data = {}
        for attribute_data in attributes_data:
            question_id = attribute_data["question"]
            attributes_by_question_id_data[question_id] = attribute_data

        for question_data in questions_data:
            question_id = question_data["id"]
            question_data["attribute"] = attributes_by_question_id_data.get(question_id, None)

            if question_data["type"] == "boolean":
                question_data["suggested_responses"] = ["Yes", "No"]

        return questions_data


