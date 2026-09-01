from django.db import migrations, models


def backfill_completed_at(apps, schema_editor):
    Session = apps.get_model("api", "Session")
    Session.objects.filter(completed=True, completed_at__isnull=True).update(
        completed_at=models.F("updated_at")
    )


def unfill_completed_at(apps, schema_editor):
    Session = apps.get_model("api", "Session")
    Session.objects.filter(completed_at__isnull=False).update(completed_at=None)


class Migration(migrations.Migration):

    dependencies = [
        ("api", "0057_session_abandoned"),
    ]

    operations = [
        migrations.AddField(
            model_name="session",
            name="completed_at",
            field=models.DateTimeField(blank=True, db_index=True, null=True),
        ),
        migrations.RunPython(backfill_completed_at, unfill_completed_at),
    ]
