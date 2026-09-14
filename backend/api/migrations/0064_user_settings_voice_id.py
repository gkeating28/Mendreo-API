from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("api", "0063_scale_submission"),
    ]

    operations = [
        migrations.AddField(
            model_name="usersettings",
            name="voice_id",
            field=models.CharField(
                choices=[
                    ("male_irish", "Male"),
                    ("female_irish", "Female"),
                ],
                default="female_irish",
                max_length=16,
            ),
        ),
    ]
