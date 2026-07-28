# Generated manually for performance indexes

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("api", "0046_charfield_max_length_fix"),
    ]

    operations = [
        migrations.AddIndex(
            model_name="session",
            index=models.Index(
                fields=["consumer", "created_at"],
                name="session_consumer_created_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="session",
            index=models.Index(
                fields=["consumer", "exercise", "created_at"],
                name="session_cons_ex_created_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="message",
            index=models.Index(
                fields=["session", "created_at"],
                name="message_session_created_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="participant",
            index=models.Index(
                fields=["session", "consumer"],
                name="participant_session_cons_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="participant",
            index=models.Index(
                fields=["session", "agent"],
                name="participant_session_agent_idx",
            ),
        ),
    ]
