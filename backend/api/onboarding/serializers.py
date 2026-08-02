from rest_framework import serializers

from ..utils import Constants


class OnboardingAnswerItemSerializer(serializers.Serializer):
    knowledge_question_id = serializers.CharField(required=False)
    question_id = serializers.CharField(required=False)
    value = serializers.JSONField()

    def validate(self, attrs):
        if not attrs.get("knowledge_question_id") and not attrs.get("question_id"):
            raise serializers.ValidationError(
                "Provide knowledge_question_id (or question_id)."
            )
        return attrs


class OnboardingAnswersSerializer(serializers.Serializer):
    variant = serializers.ChoiceField(choices=Constants.KNOWLEDGE_FLOWS)
    answers = OnboardingAnswerItemSerializer(many=True)
    complete = serializers.BooleanField(required=False, default=True)
