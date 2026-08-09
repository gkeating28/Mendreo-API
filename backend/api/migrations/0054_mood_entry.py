# Generated manually for dedicated mood check-in tracking

import charidfield.fields
import cuid
import django.core.validators
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("api", "0053_alter_agent_model_default"),
    ]

    operations = [
        migrations.CreateModel(
            name="MoodEntry",
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
                        prefix="mood_",
                        primary_key=True,
                        serialize=False,
                        unique=True,
                    ),
                ),
                (
                    "mood_score",
                    models.PositiveSmallIntegerField(
                        validators=[
                            django.core.validators.MinValueValidator(1),
                            django.core.validators.MaxValueValidator(5),
                        ],
                    ),
                ),
                ("note", models.TextField(blank=True, default="")),
                (
                    "consumer",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="mood_entries",
                        to="api.consumer",
                    ),
                ),
            ],
            options={
                "verbose_name_plural": "mood entries",
                "abstract": False,
            },
        ),
        migrations.AddIndex(
            model_name="moodentry",
            index=models.Index(
                fields=["consumer", "-created_at"],
                name="api_moodent_consume_created_idx",
            ),
        ),
    ]
