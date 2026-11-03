import cuid
import charidfield.fields
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("api", "0084_session_source_run"),
    ]

    operations = [
        migrations.CreateModel(
            name="UserInsight",
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
                        prefix="uins_",
                        primary_key=True,
                        serialize=False,
                        unique=True,
                    ),
                ),
                ("text", models.TextField()),
                ("topic_key", models.CharField(max_length=255)),
                ("generated_at", models.DateTimeField()),
                ("last_shown_at", models.DateTimeField(blank=True, null=True)),
                ("show_count", models.PositiveIntegerField(default=0)),
                ("in_hand", models.BooleanField(default=False)),
                ("retired_at", models.DateTimeField(blank=True, null=True)),
                (
                    "consumer",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="insights",
                        to="api.consumer",
                    ),
                ),
                (
                    "source_run",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="sourced_insights",
                        to="api.session",
                    ),
                ),
            ],
            options={
                "indexes": [
                    models.Index(fields=["consumer", "generated_at"], name="api_uins_cons_gen_idx"),
                    models.Index(fields=["consumer", "last_shown_at"], name="api_uins_cons_shown_idx"),
                    models.Index(fields=["consumer", "in_hand"], name="api_uins_cons_hand_idx"),
                ],
            },
        ),
        migrations.CreateModel(
            name="UserInsightCursor",
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
                        prefix="uicur_",
                        primary_key=True,
                        serialize=False,
                        unique=True,
                    ),
                ),
                ("source_fingerprint", models.CharField(max_length=64)),
                ("checked_at", models.DateTimeField()),
                (
                    "consumer",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="insight_cursor",
                        to="api.consumer",
                    ),
                ),
            ],
            options={
                "abstract": False,
            },
        ),
    ]
