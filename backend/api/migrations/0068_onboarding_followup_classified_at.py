from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("api", "0067_onboarding_followup_consent"),
    ]

    operations = [
        migrations.AddField(
            model_name="consumer",
            name="onboarding_followup_classified_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
