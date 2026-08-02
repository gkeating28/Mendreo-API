# Generated manually for Slice D — Onboarding & Refresh flows

import django.contrib.postgres.fields
from django.db import migrations, models

import api.utils.Fields


class Migration(migrations.Migration):

    dependencies = [
        ("api", "0050_pre_exercise_prompt"),
    ]

    operations = [
        migrations.AddField(
            model_name="consumer",
            name="last_onboarding_flow_completed_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="consumer",
            name="last_onboarding_flow_variant",
            field=models.CharField(blank=True, max_length=32, null=True),
        ),
        migrations.AddField(
            model_name="knowledgequestion",
            name="order_by_flow",
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddField(
            model_name="knowledgequestion",
            name="response_type",
            field=api.utils.Fields.EnumField(
                choices=[
                    ("text", "text"),
                    ("single_choice", "single_choice"),
                    ("multiple_choice", "multiple_choice"),
                    ("slider", "slider"),
                ],
                default="text",
            ),
        ),
        migrations.AddField(
            model_name="knowledgequestion",
            name="anchor_labels",
            field=django.contrib.postgres.fields.ArrayField(
                base_field=models.CharField(blank=True, max_length=64),
                blank=True,
                null=True,
                size=2,
            ),
        ),
        migrations.AddField(
            model_name="knowledgequestion",
            name="value_labels",
            field=django.contrib.postgres.fields.ArrayField(
                base_field=models.CharField(blank=True, max_length=64),
                blank=True,
                null=True,
                size=11,
            ),
        ),
        migrations.AddField(
            model_name="knowledgequestion",
            name="min_selections",
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="knowledgequestion",
            name="max_selections",
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="question",
            name="anchor_labels",
            field=django.contrib.postgres.fields.ArrayField(
                base_field=models.CharField(blank=True, max_length=64),
                blank=True,
                null=True,
                size=2,
            ),
        ),
        migrations.AddField(
            model_name="question",
            name="value_labels",
            field=django.contrib.postgres.fields.ArrayField(
                base_field=models.CharField(blank=True, max_length=64),
                blank=True,
                null=True,
                size=11,
            ),
        ),
        migrations.AddField(
            model_name="question",
            name="min_selections",
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="question",
            name="max_selections",
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
        migrations.AlterField(
            model_name="question",
            name="type",
            field=api.utils.Fields.EnumField(
                choices=[
                    ("text", "text"),
                    ("date", "date"),
                    ("number", "number"),
                    ("boolean", "boolean"),
                    ("single_choice", "single_choice"),
                    ("multiple_choice", "multiple_choice"),
                    ("slider", "slider"),
                ],
                default="text",
            ),
        ),
    ]
