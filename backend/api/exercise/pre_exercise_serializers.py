from rest_framework import serializers


class PreExerciseTestSerializer(serializers.Serializer):
    consumer_id = serializers.CharField()
    run_dry_run = serializers.BooleanField(required=False, default=False)
