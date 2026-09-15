from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("api", "0065_userobservation_dismissed_at"),
    ]

    operations = [
        migrations.AddField(
            model_name="consumer",
            name="onboarding_followup_consumed_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="knowledgeentry",
            name="needs_followup",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="knowledgeentry",
            name="followup_attempts",
            field=models.PositiveSmallIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="knowledgeentry",
            name="followup_prompt",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.AddIndex(
            model_name="knowledgeentry",
            index=models.Index(
                fields=["consumer", "needs_followup"],
                name="knowledge_entry_followup_idx",
            ),
        ),
    ]
