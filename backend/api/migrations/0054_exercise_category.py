# Generated manually — exercise category for create + list filtering

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("api", "0053_alter_agent_model_default"),
    ]

    operations = [
        migrations.AddField(
            model_name="exercise",
            name="category",
            field=models.CharField(blank=True, default="", max_length=255),
        ),
    ]
