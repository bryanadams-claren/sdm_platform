"""
Migration to set up LangGraph PostgresSaver checkpoints table.
"""

from django.db import migrations


def setup_checkpointer(apps, schema_editor):
    """Initialize the PostgresSaver checkpoints table."""
    from langgraph.checkpoint.postgres import PostgresSaver
    
    from sdm_platform.llmchat.utils.graph import get_postgres_checkpointer  # pyright: ignore[reportAttributeAccessIssue]
    
    # Get the checkpointer and call setup to create the table
    checkpointer = get_postgres_checkpointer()
    checkpointer.setup()  # pyright: ignore[reportAttributeAccessIssue]


def teardown_checkpointer(apps, schema_editor):
    """Drop the checkpoints table on migration rollback."""
    # Use raw SQL to drop the table if needed
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("DROP TABLE IF EXISTS checkpoints CASCADE")


class Migration(migrations.Migration):
    dependencies = [
        ("llmchat", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(
            setup_checkpointer,
            reverse_code=teardown_checkpointer,
        ),
    ]
