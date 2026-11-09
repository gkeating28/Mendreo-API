from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("api", "0091_invite_codes"),
    ]

    operations = [
        # Database default so inserts from code that does not know this
        # column still succeed on the shared dev database.
        migrations.AddField(
            model_name="consumer",
            name="crisis_notice_pending",
            field=models.BooleanField(default=False, db_default=False),
        ),
    ]
