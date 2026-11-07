from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("api", "0088_message_step_no"),
    ]

    operations = [
        migrations.AddField(
            model_name="session",
            name="resume_dismissed_at",
            field=models.DateTimeField(
                blank=True, null=True, default=None, db_default=None
            ),
        ),
    ]
