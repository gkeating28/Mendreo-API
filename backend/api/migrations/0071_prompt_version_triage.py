from django.db import migrations


def seed_triage_prompt(apps, schema_editor):
    from api.utils import Constants

    PromptVersion = apps.get_model("api", "PromptVersion")
    if PromptVersion.objects.filter(key=Constants.PROMPT_KEY_TRIAGE, active=True).exists():
        return
    latest = (
        PromptVersion.objects.filter(key=Constants.PROMPT_KEY_TRIAGE)
        .order_by("-version")
        .first()
    )
    version = (latest.version + 1) if latest else 1
    PromptVersion.objects.create(
        key=Constants.PROMPT_KEY_TRIAGE,
        body=Constants.PROMPT_TRIAGE,
        version=version,
        active=True,
    )


class Migration(migrations.Migration):

    dependencies = [
        ("api", "0070_wp1_additive_schema"),
    ]

    operations = [
        migrations.RunPython(seed_triage_prompt, migrations.RunPython.noop),
    ]
