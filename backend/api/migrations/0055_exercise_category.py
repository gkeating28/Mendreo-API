# Renumbered after merge conflict: both mood (#41) and exercise (#42) PRs
# shipped as 0054. Production applied 0054_mood_entry; migrate then failed
# with two leaf nodes. This replaces 0054_exercise_category.
#
# Idempotent: some preview/local DBs may already have the column and/or a
# django_migrations row for the old 0054_exercise_category name.

from django.db import migrations, models


def _cleanup_old_migration_row(apps, schema_editor):
    # Remove the superseded leaf migration name if a preview/local DB recorded it.
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            "DELETE FROM django_migrations WHERE app = %s AND name = %s",
            ["api", "0054_exercise_category"],
        )


def _noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("api", "0054_mood_entry"),
    ]

    operations = [
        migrations.RunPython(_cleanup_old_migration_row, _noop_reverse),
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AddField(
                    model_name="exercise",
                    name="category",
                    field=models.CharField(blank=True, default="", max_length=255),
                ),
            ],
            database_operations=[
                migrations.RunSQL(
                    sql=(
                        "ALTER TABLE api_exercise "
                        "ADD COLUMN IF NOT EXISTS category varchar(255) "
                        "DEFAULT '' NOT NULL;"
                    ),
                    reverse_sql=(
                        "ALTER TABLE api_exercise "
                        "DROP COLUMN IF EXISTS category;"
                    ),
                ),
            ],
        ),
    ]
