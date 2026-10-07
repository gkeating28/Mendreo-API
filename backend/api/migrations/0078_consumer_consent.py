import charidfield.fields
import cuid
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("api", "0077_user_settings_auto_read_replies"),
    ]

    operations = [
        migrations.CreateModel(
            name="ConsumerConsent",
            fields=[
                (
                    "id",
                    charidfield.fields.CharIDField(
                        default=cuid.cuid,
                        help_text="cuid-format identifier for this entity.",
                        max_length=40,
                        prefix="cnst_",
                        primary_key=True,
                        serialize=False,
                        unique=True,
                    ),
                ),
                ("version", models.CharField(max_length=32)),
                ("age_confirmed", models.BooleanField()),
                ("age_confirmed_at", models.DateTimeField()),
                ("limitations_acknowledged", models.BooleanField()),
                ("limitations_acknowledged_at", models.DateTimeField()),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "consumer",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="consents",
                        to="api.consumer",
                    ),
                ),
            ],
        ),
        migrations.AddConstraint(
            model_name="consumerconsent",
            constraint=models.UniqueConstraint(
                fields=("consumer", "version"),
                name="unique_consumer_consent_version",
            ),
        ),
        migrations.CreateModel(
            name="ConsumerMarketingOptIn",
            fields=[
                (
                    "id",
                    charidfield.fields.CharIDField(
                        default=cuid.cuid,
                        help_text="cuid-format identifier for this entity.",
                        max_length=40,
                        prefix="mkto_",
                        primary_key=True,
                        serialize=False,
                        unique=True,
                    ),
                ),
                ("version", models.CharField(max_length=32)),
                ("opted_in", models.BooleanField()),
                ("opted_in_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "consumer",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="marketing_opt_ins",
                        to="api.consumer",
                    ),
                ),
            ],
        ),
        migrations.AddConstraint(
            model_name="consumermarketingoptin",
            constraint=models.UniqueConstraint(
                fields=("consumer", "version"),
                name="unique_consumer_marketing_opt_in_version",
            ),
        ),
    ]
