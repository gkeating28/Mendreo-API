from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("api", "0086_session_opener"),
    ]

    operations = [
        migrations.AddField(
            model_name="turnprompt",
            name="decisions",
            field=models.JSONField(blank=True, db_default=[], default=list),
        ),
    ]
