from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("api", "0075_wp8_cleanup"),
    ]

    operations = [
        migrations.AddIndex(
            model_name="session",
            index=models.Index(
                fields=["consumer", "completed", "completed_at"],
                name="session_cons_completed_at_idx",
            ),
        ),
    ]
