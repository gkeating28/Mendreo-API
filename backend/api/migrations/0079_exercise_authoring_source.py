from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("api", "0078_authoring_test_flags"),
    ]

    operations = [
        migrations.AddField(
            model_name="exercise",
            name="authoring_source",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=models.deletion.CASCADE,
                related_name="authoring_snapshots",
                to="api.exercise",
            ),
        ),
    ]
