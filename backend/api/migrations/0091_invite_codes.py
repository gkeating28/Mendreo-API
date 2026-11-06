import charidfield.fields
import cuid
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("api", "0090_welcome_flow"),
    ]

    operations = [
        # Nullable with a database default so main's consumer inserts, which
        # do not mention this column, still succeed on the shared dev DB.
        migrations.AddField(
            model_name="consumer",
            name="signup_source",
            field=models.CharField(
                blank=True,
                null=True,
                max_length=32,
                default="register",
                db_default="register",
            ),
        ),
        migrations.CreateModel(
            name="InviteCode",
            fields=[
                ("deleted_at", models.DateTimeField(blank=True, db_index=True, null=True)),
                ("updated_at", models.DateTimeField(auto_now=True, db_index=True)),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                (
                    "id",
                    charidfield.fields.CharIDField(
                        default=cuid.cuid,
                        help_text="cuid-format identifier for this entity.",
                        max_length=40,
                        prefix="ivc_",
                        primary_key=True,
                        serialize=False,
                        unique=True,
                    ),
                ),
                ("code", models.CharField(max_length=8, unique=True)),
                ("label", models.CharField(blank=True, default="", max_length=255)),
                ("expires_at", models.DateTimeField(blank=True, null=True)),
                ("active", models.BooleanField(db_default=True, default=True)),
                ("redeemed_at", models.DateTimeField(blank=True, null=True)),
                (
                    "consumer",
                    models.OneToOneField(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="invite_code",
                        to="api.consumer",
                    ),
                ),
                (
                    "created_by",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="invite_codes_created",
                        to="api.user",
                    ),
                ),
            ],
            options={
                "abstract": False,
            },
        ),
    ]
