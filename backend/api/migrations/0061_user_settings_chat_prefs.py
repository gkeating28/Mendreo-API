from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("api", "0060_user_settings"),
    ]

    operations = [
        migrations.AddField(
            model_name="usersettings",
            name="chat_speed",
            field=models.CharField(
                choices=[
                    ("instant", "Instant"),
                    ("normal", "Normal"),
                    ("slow", "Slow"),
                ],
                default="normal",
                max_length=16,
            ),
        ),
        migrations.AddField(
            model_name="usersettings",
            name="chat_text_size",
            field=models.CharField(
                choices=[
                    ("small", "Small"),
                    ("medium", "Medium"),
                    ("large", "Large"),
                    ("xlarge", "Xlarge"),
                ],
                default="medium",
                max_length=16,
            ),
        ),
    ]
