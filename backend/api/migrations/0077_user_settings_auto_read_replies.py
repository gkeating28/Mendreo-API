from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("api", "0076_session_consumer_completed_at_index"),
    ]

    operations = [
        migrations.AddField(
            model_name="usersettings",
            name="auto_read_replies",
            field=models.BooleanField(default=False),
        ),
    ]
