from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("api", "0068_onboarding_followup_classified_at"),
    ]

    operations = [
        migrations.AlterField(
            model_name="usersettings",
            name="voice_id",
            field=models.CharField(
                choices=[
                    ("male_irish", "Male - Irish"),
                    ("female_irish", "Female - Irish"),
                    ("american_male", "Male - American"),
                    ("american_female", "Female - American"),
                    ("british_female", "Female - British"),
                    ("british_male", "Male - British"),
                ],
                default="female_irish",
                max_length=16,
            ),
        ),
    ]
