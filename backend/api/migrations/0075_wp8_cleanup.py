from django.db import migrations, models


PROMPT_KEYS = (
    "general_prompt",
    "therapeutic_prompt",
    "observations_instruction",
    "observations_tone_guide",
)


def copy_forward(apps, schema_editor):
    Exercise = apps.get_model("api", "Exercise")
    for exercise in Exercise.objects.all():
        exercise.check_in_enabled = exercise.pre_exercise_enabled
        exercise.check_in_tone = exercise.pre_exercise_description
        exercise.check_in_instruction = exercise.pre_exercise_instruction
        exercise.check_in_goal = exercise.pre_exercise_goal
        exercise.check_in_summary_prompt = exercise.pre_exercise_completion_prompt
        exercise.check_in_start_button_label = exercise.pre_exercise_start_button_label or "Start exercise"
        exercise.save(
            update_fields=[
                "check_in_enabled",
                "check_in_tone",
                "check_in_instruction",
                "check_in_goal",
                "check_in_summary_prompt",
                "check_in_start_button_label",
            ]
        )

    Step = apps.get_model("api", "Step")
    for step in Step.objects.all():
        if not (step.done_when or "").strip() and step.completion_criteria:
            step.done_when = step.completion_criteria
            step.save(update_fields=["done_when"])

    Setting = apps.get_model("api", "Setting")
    Setting.objects.filter(key__in=PROMPT_KEYS).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("api", "0074_wp7_session_close"),
    ]

    operations = [
        migrations.RunPython(copy_forward, migrations.RunPython.noop),
        migrations.RemoveField(model_name="message", name="is_step_complete"),
        migrations.RemoveField(model_name="message", name="step_no"),
        migrations.RemoveField(model_name="message", name="completion_result"),
        migrations.RemoveField(model_name="exercise", name="pre_exercise_enabled"),
        migrations.RemoveField(model_name="exercise", name="pre_exercise_description"),
        migrations.RemoveField(model_name="exercise", name="pre_exercise_instruction"),
        migrations.RemoveField(model_name="exercise", name="pre_exercise_goal"),
        migrations.RemoveField(model_name="exercise", name="pre_exercise_completion_prompt"),
        migrations.RemoveField(model_name="exercise", name="pre_exercise_start_button_label"),
        migrations.RemoveField(model_name="step", name="completion_criteria"),
        migrations.RemoveField(model_name="session", name="cached_history"),
        migrations.RemoveField(model_name="knowledgeentry", name="attribute"),
        migrations.DeleteModel(name="Attribute"),
    ]
