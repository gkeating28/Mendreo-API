from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("api", "0078_consumer_consent"),
    ]

    operations = [
        migrations.AddField(
            model_name="exercise",
            name="authoring_snapshot",
            field=models.BooleanField(db_index=True, default=False),
        ),
    ]
