from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("api", "0089_session_resume_dismissed_at"),
    ]

    operations = [
        migrations.AddField(
            model_name="consumer",
            name="welcome_completed_at",
            field=models.DateTimeField(
                blank=True, null=True, default=None, db_default=None
            ),
        ),
        migrations.AddField(
            model_name="knowledgefield",
            name="sync_to",
            field=models.CharField(
                blank=True,
                null=True,
                max_length=32,
                default="none",
                db_default=None,
            ),
        ),
        migrations.AddField(
            model_name="knowledgequestion",
            name="chip_replies",
            field=models.JSONField(
                blank=True, null=True, default=dict, db_default=None
            ),
        ),
    ]
