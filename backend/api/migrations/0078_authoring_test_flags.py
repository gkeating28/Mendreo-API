from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("api", "0077_user_settings_auto_read_replies"),
    ]

    operations = [
        migrations.AddField(
            model_name="session",
            name="authoring_test",
            field=models.BooleanField(db_index=True, default=False),
        ),
        migrations.AddField(
            model_name="exercise",
            name="authoring_snapshot",
            field=models.BooleanField(db_index=True, default=False),
        ),
    ]
