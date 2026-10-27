from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("api", "0081_turn_prompt"),
    ]

    operations = [
        migrations.AddField(
            model_name="message",
            name="retrieval_skipped",
            field=models.CharField(blank=True, default="", max_length=32),
        ),
    ]
