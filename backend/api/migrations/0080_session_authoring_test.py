from django.db import migrations, models


def add_authoring_test(apps, schema_editor):
    """Add the column when this database does not already have it.

    The shared database gained ``authoring_test`` from a migration that is
    not in this repository. A plain AddField fails there because the column
    exists and is NOT NULL with no default, which is what rejects session
    inserts. Databases created from these migrations still need the column.
    """
    connection = schema_editor.connection
    table = apps.get_model("api", "Session")._meta.db_table
    with connection.cursor() as cursor:
        columns = {
            column.name
            for column in connection.introspection.get_table_description(cursor, table)
        }
    if "authoring_test" in columns:
        if connection.vendor == "postgresql":
            schema_editor.execute(
                f'ALTER TABLE "{table}" ALTER COLUMN authoring_test SET DEFAULT false'
            )
        return

    if connection.vendor == "postgresql":
        schema_editor.execute(
            f'ALTER TABLE "{table}" '
            "ADD COLUMN authoring_test boolean NOT NULL DEFAULT false"
        )
        return
    schema_editor.execute(
        f'ALTER TABLE "{table}" ADD COLUMN authoring_test bool NOT NULL DEFAULT 0'
    )


class Migration(migrations.Migration):

    dependencies = [
        ("api", "0079_knowledge_index_status"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AddField(
                    model_name="session",
                    name="authoring_test",
                    field=models.BooleanField(db_default=False, default=False),
                ),
            ],
            database_operations=[
                migrations.RunPython(add_authoring_test, migrations.RunPython.noop),
            ],
        ),
    ]
