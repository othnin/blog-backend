from django.db import migrations

# The app used to be labelled ``thales``, so existing databases have tables
# with that prefix. Fresh databases (built from the rewritten 0001–0006) create
# the ``watsoncrick_*`` names directly. This migration handles both.
MODELS = (
    'lesson',
    'studentprogress',
    'assistantinteraction',
    'modelexperiment',
    'advisorsession',
    'hypothesisnote',
    'studentgrade',
    'advisorfeedback',
)

# Fresh databases inherit the first name from 0001; existing databases keep
# the old one. Both are renamed to the name the current model Meta implies.
INDEX_OLD_NAMES = (
    'thales_advi_student_6e23ac_idx',
    'watsoncrick_advi_student_6e23ac_idx',
)
INDEX_NEW_NAME = 'watsoncrick_student_f3e9d4_idx'


def _index_exists(schema_editor, name):
    vendor = schema_editor.connection.vendor
    with schema_editor.connection.cursor() as cursor:
        if vendor == 'postgresql':
            cursor.execute(
                "SELECT 1 FROM pg_class WHERE relname = %s AND relkind = 'i'", [name]
            )
        elif vendor == 'sqlite':
            cursor.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'index' AND name = %s", [name]
            )
        else:
            return False
        return cursor.fetchone() is not None


def _rename_index(schema_editor, old, new):
    # SQLite has no ALTER INDEX ... RENAME TO in the versions we support. An
    # index name is only a label for the ORM, so leaving the legacy name there
    # is harmless; PostgreSQL gets the tidy rename.
    if schema_editor.connection.vendor != 'postgresql':
        return
    if _index_exists(schema_editor, old) and not _index_exists(schema_editor, new):
        schema_editor.execute(
            f'ALTER INDEX {schema_editor.quote_name(old)} RENAME TO {schema_editor.quote_name(new)}'
        )


def _rename_tables(apps, schema_editor, source, target):
    qn = schema_editor.quote_name
    tables = set(schema_editor.connection.introspection.table_names())
    for model in MODELS:
        old = f'{source}{model}'
        new = f'{target}{model}'
        if old in tables and new not in tables:
            schema_editor.execute(f'ALTER TABLE {qn(old)} RENAME TO {qn(new)}')

    for old_index in INDEX_OLD_NAMES:
        _rename_index(schema_editor, old_index, INDEX_NEW_NAME)


def forwards(apps, schema_editor):
    _rename_tables(apps, schema_editor, 'thales_', 'watsoncrick_')


def backwards(apps, schema_editor):
    # Restore the legacy names when rolling this migration back.
    _rename_tables(apps, schema_editor, 'watsoncrick_', 'thales_')
    # Restore the legacy index name when rolling back (PostgreSQL only).
    _rename_index(schema_editor, INDEX_NEW_NAME, INDEX_OLD_NAMES[0])


class Migration(migrations.Migration):
    dependencies = [
        ('watsoncrick', '0006_studentgrade_alter_lesson_options_advisorfeedback'),
    ]

    operations = [
        # The physical renames are conditional (RunPython); the state changes
        # are unconditional so the model Meta stays in sync with the schema.
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.RenameIndex(
                    model_name='advisorfeedback',
                    new_name='watsoncrick_student_f3e9d4_idx',
                    old_name='watsoncrick_advi_student_6e23ac_idx',
                ),
                *[
                    migrations.AlterModelTable(name=model, table=f'watsoncrick_{model}')
                    for model in MODELS
                ],
            ],
            database_operations=[
                migrations.RunPython(forwards, backwards),
            ],
        ),
    ]
