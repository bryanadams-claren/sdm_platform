"""
Migration to set up LangGraph PostgresStore tables for memory management.
"""

from django.db import migrations


def setup_store(apps, schema_editor):
    """Initialize the PostgresStore tables."""
    import environ
    from langgraph.store.postgres import PostgresStore

    env = environ.Env()

    with PostgresStore.from_conn_string(env.str("DATABASE_URL")) as store:
        store.setup()


def teardown_store(apps, schema_editor):
    """Drop the store tables on migration rollback."""
    with schema_editor.connection.cursor() as cursor:
        # LangGraph PostgresStore creates these tables
        cursor.execute("DROP TABLE IF EXISTS store CASCADE")


class Migration(migrations.Migration):
    dependencies = [
        # Ensure checkpointer tables exist first
        ("llmchat", "0100_langgraph_checkpointer"),
    ]

    operations = [
        migrations.RunPython(
            setup_store,
            reverse_code=teardown_store,
        ),
    ]
