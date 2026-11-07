import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("api", "0083_merge_0082"),
    ]

    operations = [
        migrations.AddField(
            model_name="session",
            name="source_run",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="reflection_chats",
                to="api.session",
            ),
        ),
    ]
