# Generated manually for Slice E — Progress & Insights

import charidfield.fields
import cuid
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("api", "0051_onboarding_refresh_flows"),
    ]

    operations = [
        migrations.CreateModel(
            name="UserObservation",
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
                        prefix="uobs_",
                        primary_key=True,
                        serialize=False,
                        unique=True,
                    ),
                ),
                ("text", models.TextField()),
                ("topic_tag", models.CharField(blank=True, default="", max_length=255)),
                ("generated_at", models.DateTimeField()),
                (
                    "consumer",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="observations",
                        to="api.consumer",
                    ),
                ),
            ],
            options={
                "abstract": False,
            },
        ),
        migrations.AddIndex(
            model_name="userobservation",
            index=models.Index(
                fields=["consumer", "-generated_at"],
                name="api_userobs_consume_gen_idx",
            ),
        ),
    ]
