import charidfield.fields
import cuid
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("api", "0058_session_completed_at"),
    ]

    operations = [
        migrations.CreateModel(
            name="ExerciseReflection",
            fields=[
                ("deleted_at", models.DateTimeField(blank=True, db_index=True, null=True)),
                ("updated_at", models.DateTimeField(auto_now=True, db_index=True)),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                (
                    "id",
                    charidfield.fields.CharIDField(
                        default=cuid.cuid,
                        help_text="cuid-format identifier for this entity.",
                        max_length=40,
                        prefix="rflc_",
                        primary_key=True,
                        serialize=False,
                        unique=True,
                    ),
                ),
                ("step_id", models.CharField(max_length=64)),
                ("text", models.TextField()),
                (
                    "consumer",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="exercise_reflections",
                        to="api.consumer",
                    ),
                ),
                (
                    "session",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="reflections",
                        to="api.session",
                    ),
                ),
            ],
            options={
                "abstract": False,
            },
        ),
        migrations.AddIndex(
            model_name="exercisereflection",
            index=models.Index(fields=["session", "step_id"], name="api_rflc_session_step_idx"),
        ),
        migrations.AddIndex(
            model_name="exercisereflection",
            index=models.Index(
                fields=["consumer", "-updated_at"],
                name="api_rflc_consumer_upd_idx",
            ),
        ),
    ]
