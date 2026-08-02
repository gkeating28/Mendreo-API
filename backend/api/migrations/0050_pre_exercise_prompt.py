# Generated manually for Slice C — Pre-Exercise Prompt

from django.db import migrations, models


def disable_pre_exercise_on_existing(apps, schema_editor):
    """Existing exercises lack authored check-in copy; keep them off until configured."""
    Exercise = apps.get_model("api", "Exercise")
    Exercise.objects.all().update(pre_exercise_enabled=False)


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("api", "0049_knowledge_engine_and_permissions"),
    ]

    operations = [
        migrations.AddField(
            model_name="exercise",
            name="pre_exercise_enabled",
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name="exercise",
            name="pre_exercise_description",
            field=models.TextField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="exercise",
            name="pre_exercise_instruction",
            field=models.TextField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="exercise",
            name="pre_exercise_goal",
            field=models.TextField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="exercise",
            name="pre_exercise_completion_prompt",
            field=models.TextField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="exercise",
            name="pre_exercise_start_button_label",
            field=models.CharField(blank=True, default="Start exercise", max_length=24),
        ),
        migrations.AddField(
            model_name="session",
            name="pre_exercise_prompt_summary",
            field=models.TextField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="session",
            name="pre_exercise_completed_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.RunPython(disable_pre_exercise_on_existing, noop_reverse),
    ]
