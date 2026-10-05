from rest_framework import serializers


class PreExerciseTestSerializer(serializers.Serializer):
    consumer_id = serializers.CharField()
    run_dry_run = serializers.BooleanField(required=False, default=False)
    transcript = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    check_in_tone = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    check_in_instruction = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    check_in_goal = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    check_in_summary_prompt = serializers.CharField(
        required=False, allow_blank=True, allow_null=True
    )
