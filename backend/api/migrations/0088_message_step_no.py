from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("api", "0087_turn_prompt_decisions"),
    ]

    operations = [
        migrations.AddField(
            model_name="message",
            name="step_no",
            field=models.PositiveIntegerField(blank=True, db_default=None, null=True),
        ),
    ]
