# Generated manually for user-level settings

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("api", "0059_exercise_reflection"),
    ]

    operations = [
        migrations.CreateModel(
            name="UserSettings",
            fields=[
                ("deleted_at", models.DateTimeField(blank=True, db_index=True, null=True)),
                ("updated_at", models.DateTimeField(auto_now=True, db_index=True)),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                (
                    "user",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        primary_key=True,
                        related_name="settings",
                        serialize=False,
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                ("timezone", models.CharField(default="UTC", max_length=64)),
                ("notification_push_enabled", models.BooleanField(default=True)),
                ("notification_daily_reminder_enabled", models.BooleanField(default=False)),
                ("notification_daily_reminder_time", models.TimeField(blank=True, null=True)),
            ],
            options={
                "abstract": False,
            },
        ),
    ]
