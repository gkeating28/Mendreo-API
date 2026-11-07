from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("api", "0085_user_insight"),
    ]

    operations = [
        migrations.AddField(
            model_name="session",
            name="opener",
            field=models.TextField(blank=True, null=True),
        ),
    ]
