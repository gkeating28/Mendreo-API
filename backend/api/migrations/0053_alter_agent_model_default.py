from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("api", "0052_user_observation_and_settings"),
    ]

    operations = [
        migrations.AlterField(
            model_name="agent",
            name="model",
            field=models.CharField(default="gemini-3.1-flash-lite", max_length=255),
        ),
    ]
