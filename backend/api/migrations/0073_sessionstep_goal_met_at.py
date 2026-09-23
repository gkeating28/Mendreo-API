from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("api", "0072_wp3_history_and_resources"),
    ]

    operations = [
        migrations.AddField(
            model_name="sessionstep",
            name="goal_met_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
