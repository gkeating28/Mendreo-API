from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("api", "0078_knowledge_grounding"),
    ]

    operations = [
        migrations.AddField(
            model_name="knowledgesource",
            name="index_status",
            field=models.CharField(default="idle", max_length=16),
        ),
        migrations.AddField(
            model_name="knowledgesource",
            name="index_error",
            field=models.TextField(blank=True, default=""),
        ),
    ]
