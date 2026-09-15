from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("api", "0064_user_settings_voice_id"),
    ]

    operations = [
        migrations.AddField(
            model_name="userobservation",
            name="dismissed_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
