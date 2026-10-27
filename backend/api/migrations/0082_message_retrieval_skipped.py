from django.db import migrations, models


def deactivate_case_material(apps, schema_editor):
    from api.grounding.case_material import case_material_reason

    Chunk = apps.get_model("api", "KnowledgeChunk")
    matched = []
    for chunk in Chunk.objects.filter(active=True).only("id", "heading_path", "text").iterator():
        if case_material_reason(chunk.heading_path or "", chunk.text or ""):
            matched.append(chunk.id)
    if matched:
        Chunk.objects.filter(id__in=matched).update(active=False)


class Migration(migrations.Migration):

    dependencies = [
        ("api", "0081_turn_prompt"),
    ]

    operations = [
        migrations.AddField(
            model_name="message",
            name="retrieval_skipped",
            field=models.CharField(blank=True, default="", max_length=32),
        ),
        migrations.RunPython(deactivate_case_material, migrations.RunPython.noop),
    ]
