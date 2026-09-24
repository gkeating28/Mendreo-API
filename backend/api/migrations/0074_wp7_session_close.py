import django.db.models.deletion
from django.contrib.postgres.fields import ArrayField
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("api", "0073_sessionstep_goal_met_at"),
    ]

    operations = [
        migrations.AddField(
            model_name="session",
            name="close_reason",
            field=models.CharField(blank=True, max_length=64, null=True),
        ),
        migrations.AddField(
            model_name="session",
            name="pending_knowledge_question",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="sessions",
                to="api.knowledgequestion",
            ),
        ),
        migrations.AlterField(
            model_name="knowledgequestion",
            name="flows",
            field=ArrayField(
                base_field=models.CharField(max_length=255),
                blank=True,
                default=list,
                size=None,
            ),
        ),
    ]
