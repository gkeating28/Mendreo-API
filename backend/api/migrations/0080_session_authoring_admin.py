from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("api", "0079_exercise_authoring_source"),
    ]

    operations = [
        migrations.AddField(
            model_name="session",
            name="authoring_admin",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=models.deletion.SET_NULL,
                related_name="authoring_test_runs",
                to="api.admin",
            ),
        ),
    ]
