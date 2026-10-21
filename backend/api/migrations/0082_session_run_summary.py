from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("api", "0081_turn_prompt"),
    ]

    operations = [
        migrations.AddField(
            model_name="session",
            name="run_summary",
            field=models.JSONField(blank=True, null=True),
        ),
    ]
