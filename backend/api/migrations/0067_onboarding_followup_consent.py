from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("api", "0066_onboarding_followup_fields"),
    ]

    operations = [
        migrations.AddField(
            model_name="consumer",
            name="onboarding_followup_consent",
            field=models.CharField(blank=True, max_length=16, null=True),
        ),
        migrations.AddField(
            model_name="consumer",
            name="onboarding_followup_session_id",
            field=models.CharField(blank=True, max_length=40, null=True),
        ),
    ]
