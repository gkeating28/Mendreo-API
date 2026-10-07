import api.utils.Fields
import charidfield.fields
import cuid
import django.contrib.postgres.fields
import django.contrib.postgres.indexes
import django.contrib.postgres.search
import django.db.models.deletion
import pgvector.django.extensions
import pgvector.django.indexes
import pgvector.django.vector
from django.db import migrations, models


def seed_knowledge_source_permissions(apps, schema_editor):
    Permissions = apps.get_model("api", "Permissions")
    Role = apps.get_model("api", "Role")
    defaults_by_name = {
        "Super Admin": ["view", "create", "edit", "delete", "approve"],
        "Admin": ["view", "create", "edit"],
        "Read Only": ["view"],
    }
    for role in Role.objects.all():
        if role.name not in defaults_by_name:
            continue
        try:
            perms = Permissions.objects.get(role_id=role.id)
        except Permissions.DoesNotExist:
            continue
        perms.knowledge_sources = defaults_by_name[role.name]
        perms.save(update_fields=["knowledge_sources"])


def unseed_knowledge_source_permissions(apps, schema_editor):
    Permissions = apps.get_model("api", "Permissions")
    Permissions.objects.all().update(knowledge_sources=[])


class Migration(migrations.Migration):

    dependencies = [
        ("api", "0077_user_settings_auto_read_replies"),
    ]

    operations = [
        pgvector.django.extensions.VectorExtension(),
        migrations.CreateModel(
            name="KnowledgeSource",
            fields=[
                ("deleted_at", models.DateTimeField(blank=True, db_index=True, null=True)),
                ("updated_at", models.DateTimeField(auto_now=True, db_index=True)),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                (
                    "id",
                    charidfield.fields.CharIDField(
                        default=cuid.cuid,
                        help_text="cuid-format identifier for this entity.",
                        max_length=40,
                        prefix="ksrc_",
                        primary_key=True,
                        serialize=False,
                        unique=True,
                    ),
                ),
                ("title", models.CharField(max_length=255)),
                (
                    "kind",
                    api.utils.Fields.EnumField(
                        choices=[
                            ("up_source", "up_source"),
                            ("guidance", "guidance"),
                            ("post", "post"),
                            ("exercise_reference", "exercise_reference"),
                        ],
                        default="up_source",
                    ),
                ),
                (
                    "status",
                    api.utils.Fields.EnumField(
                        choices=[
                            ("draft", "draft"),
                            ("in_review", "in_review"),
                            ("published", "published"),
                            ("retired", "retired"),
                        ],
                        default="draft",
                    ),
                ),
                ("version", models.PositiveIntegerField(default=1)),
                ("body", models.TextField(blank=True, null=True)),
                ("licence_note", models.TextField(blank=True, default="")),
                ("submitted_at", models.DateTimeField(blank=True, null=True)),
                ("approved_at", models.DateTimeField(blank=True, null=True)),
                ("exercise_ids", models.JSONField(blank=True, default=list)),
                (
                    "approved_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="knowledge_sources_approved",
                        to="api.admin",
                    ),
                ),
                (
                    "clinical_owner",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="knowledge_sources_owned",
                        to="api.admin",
                    ),
                ),
                (
                    "file",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="knowledge_sources",
                        to="api.file",
                    ),
                ),
                (
                    "post",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="knowledge_sources",
                        to="api.post",
                    ),
                ),
                (
                    "submitted_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="knowledge_sources_submitted",
                        to="api.admin",
                    ),
                ),
                (
                    "tags",
                    models.ManyToManyField(
                        blank=True,
                        related_name="knowledge_sources",
                        to="api.tag",
                    ),
                ),
            ],
            options={
                "indexes": [
                    django.contrib.postgres.indexes.GinIndex(
                        fields=["exercise_ids"],
                        name="ksrc_exercise_ids_gin",
                    )
                ],
            },
        ),
        migrations.CreateModel(
            name="KnowledgeChunk",
            fields=[
                ("deleted_at", models.DateTimeField(blank=True, db_index=True, null=True)),
                ("updated_at", models.DateTimeField(auto_now=True, db_index=True)),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                (
                    "id",
                    charidfield.fields.CharIDField(
                        default=cuid.cuid,
                        help_text="cuid-format identifier for this entity.",
                        max_length=40,
                        prefix="kchk_",
                        primary_key=True,
                        serialize=False,
                        unique=True,
                    ),
                ),
                ("source_version", models.PositiveIntegerField()),
                ("ordinal", models.PositiveIntegerField()),
                ("heading_path", models.TextField(blank=True, default="")),
                ("text", models.TextField()),
                ("token_count", models.PositiveIntegerField(default=0)),
                (
                    "embedding",
                    pgvector.django.vector.VectorField(dimensions=768),
                ),
                (
                    "search_vector",
                    models.GeneratedField(
                        db_persist=True,
                        expression=django.contrib.postgres.search.SearchVector(
                            "text", config="english"
                        ),
                        output_field=django.contrib.postgres.search.SearchVectorField(),
                    ),
                ),
                ("active", models.BooleanField(default=True)),
                (
                    "source",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="chunks",
                        to="api.knowledgesource",
                    ),
                ),
            ],
            options={
                "indexes": [
                    models.Index(
                        fields=["source", "active"],
                        name="kchunk_source_active_idx",
                    ),
                    django.contrib.postgres.indexes.GinIndex(
                        fields=["search_vector"],
                        name="kchunk_search_gin",
                    ),
                    pgvector.django.indexes.HnswIndex(
                        ef_construction=64,
                        fields=["embedding"],
                        m=16,
                        name="kchunk_embedding_hnsw",
                        opclasses=["vector_cosine_ops"],
                    ),
                ],
            },
        ),
        migrations.AddField(
            model_name="message",
            name="retrieval",
            field=models.JSONField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="permissions",
            name="knowledge_sources",
            field=django.contrib.postgres.fields.ArrayField(
                base_field=api.utils.Fields.EnumField(
                    choices=[
                        ("view", "view"),
                        ("create", "create"),
                        ("edit", "edit"),
                        ("delete", "delete"),
                        ("approve", "approve"),
                    ],
                    default="view",
                ),
                blank=True,
                default=list,
                size=None,
            ),
        ),
        migrations.RunPython(
            seed_knowledge_source_permissions,
            unseed_knowledge_source_permissions,
        ),
    ]
