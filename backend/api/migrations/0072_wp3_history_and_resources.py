import json

from django.db import migrations, models


def seed_resources_prompt(apps, schema_editor):
    from api.utils import Constants

    PromptVersion = apps.get_model("api", "PromptVersion")
    if PromptVersion.objects.filter(key=Constants.PROMPT_KEY_RESOURCES, active=True).exists():
        return
    latest = (
        PromptVersion.objects.filter(key=Constants.PROMPT_KEY_RESOURCES)
        .order_by("-version")
        .first()
    )
    version = (latest.version + 1) if latest else 1
    PromptVersion.objects.create(
        key=Constants.PROMPT_KEY_RESOURCES,
        body=json.dumps(Constants.DEFAULT_RESOURCES),
        version=version,
        active=True,
    )


class Migration(migrations.Migration):

    dependencies = [
        ("api", "0071_prompt_version_triage"),
    ]

    operations = [
        migrations.AddField(
            model_name="session",
            name="history_summary",
            field=models.TextField(blank=True, null=True),
        ),
        migrations.RunPython(seed_resources_prompt, migrations.RunPython.noop),
    ]
