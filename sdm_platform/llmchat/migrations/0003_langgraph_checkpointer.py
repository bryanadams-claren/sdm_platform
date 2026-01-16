"""
Migration to set up LangGraph PostgresSaver checkpoints table.
"""

from django.db import migrations


def setup_checkpointer(apps, schema_editor):
    """Initialize the PostgresSaver checkpoints table."""
    import environ
    from langgraph.checkpoint.postgres import PostgresSaver

    # Get the database URL directly and create the checkpointer
    env = environ.Env()

    # PostgresSaver.from_conn_string returns a context manager
    # We need to use it with 'with' statement
    with PostgresSaver.from_conn_string(env.str("DATABASE_URL")) as checkpointer:  # pyright: ignore[reportArgumentType]
        checkpointer.setup()

def teardown_checkpointer(apps, schema_editor):
    """Drop the checkpoints table on migration rollback."""
    # Use raw SQL to drop the table if needed
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("DROP TABLE IF EXISTS checkpoints CASCADE")
        # TODO: more teardown logic belongs here


class Migration(migrations.Migration):
    dependencies = [
       ("llmchat", "0002_add_user_foreign_key"),
    ]

    operations = [
        migrations.RunPython(
            setup_checkpointer,
            reverse_code=teardown_checkpointer,
        ),
    ]
