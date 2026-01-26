# Migration Squashing Script

This document provides step-by-step instructions for squashing migrations before the initial production launch.

**Prerequisites:**
- Production database has been reset (no data to preserve)
- All code changes have been deployed
- You have a local development environment ready

---

## Phase 1: Backup Custom Migration Code

Before deleting any migrations, save the custom RunPython code.

### 1.1 Backup llmchat/0003 (LangGraph Checkpointer Setup)

Save this code - it sets up the LangGraph PostgresSaver tables:

```python
# From: sdm_platform/llmchat/migrations/0003_langgraph_checkpointer.py

from django.db import migrations


def setup_checkpointer(apps, schema_editor):
    """Set up the LangGraph checkpointer tables."""
    from langgraph.checkpoint.postgres import PostgresSaver
    import environ

    env = environ.Env()
    conn_string = env.str("DATABASE_URL")

    with PostgresSaver.from_conn_string(conn_string) as checkpointer:
        checkpointer.setup()


def teardown_checkpointer(apps, schema_editor):
    """Remove the LangGraph checkpointer tables."""
    from django.db import connection

    with connection.cursor() as cursor:
        cursor.execute("DROP TABLE IF EXISTS checkpoints CASCADE;")
        cursor.execute("DROP TABLE IF EXISTS checkpoint_writes CASCADE;")
        cursor.execute("DROP TABLE IF EXISTS checkpoint_blobs CASCADE;")


class Migration(migrations.Migration):
    dependencies = [
        ("llmchat", "PREVIOUS_MIGRATION"),  # Update this
    ]

    operations = [
        migrations.RunPython(setup_checkpointer, teardown_checkpointer),
    ]
```

### 1.2 Backup memory/0002 (LangGraph Store Setup)

Save this code - it sets up the LangGraph PostgresStore tables:

```python
# From: sdm_platform/memory/migrations/0002_setup_postgres_store.py

from django.db import migrations


def setup_store(apps, schema_editor):
    """Set up the LangGraph memory store tables."""
    from langgraph.store.postgres import PostgresStore
    import environ

    env = environ.Env()
    conn_string = env.str("DATABASE_URL")

    with PostgresStore.from_conn_string(conn_string) as store:
        store.setup()


def teardown_store(apps, schema_editor):
    """Remove the LangGraph store tables."""
    from django.db import connection

    with connection.cursor() as cursor:
        cursor.execute("DROP TABLE IF EXISTS store CASCADE;")


class Migration(migrations.Migration):
    dependencies = [
        ("memory", "PREVIOUS_MIGRATION"),  # Update this
    ]

    operations = [
        migrations.RunPython(setup_store, teardown_store),
    ]
```

### 1.3 Backup journeys/0004 (Load Journeys)

Save this code - it loads journey configurations from JSON:

```python
# From: sdm_platform/journeys/migrations/0004_load_journeys.py

from django.db import migrations


def load_journeys(apps, schema_editor):
    """Load journey configurations from JSON files."""
    from django.core.management import call_command
    call_command("load_journeys")


def reverse_load_journeys(apps, schema_editor):
    """No-op reverse - journeys would need manual cleanup."""
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("memory", "MEMORY_INITIAL"),  # Needs ConversationPoint model
        ("journeys", "PREVIOUS_MIGRATION"),  # Update this
    ]

    operations = [
        migrations.RunPython(load_journeys, reverse_load_journeys),
    ]
```

---

## Phase 2: Delete Existing Migrations

Run these commands from the project root:

```powershell
# Navigate to project
cd C:\Users\Bryan\code\sdm_platform

# Delete all migration files (keeping __init__.py)
Get-ChildItem -Path "sdm_platform\users\migrations\*.py" -Exclude "__init__.py" | Remove-Item
Get-ChildItem -Path "sdm_platform\llmchat\migrations\*.py" -Exclude "__init__.py" | Remove-Item
Get-ChildItem -Path "sdm_platform\journeys\migrations\*.py" -Exclude "__init__.py" | Remove-Item
Get-ChildItem -Path "sdm_platform\memory\migrations\*.py" -Exclude "__init__.py" | Remove-Item
Get-ChildItem -Path "sdm_platform\evidence\migrations\*.py" -Exclude "__init__.py" | Remove-Item
```

---

## Phase 3: Generate Fresh Initial Migrations

Generate new migrations in dependency order:

```powershell
# 1. Users first (no dependencies)
uv run python manage.py makemigrations users --name initial

# 2. Evidence (depends on users)
uv run python manage.py makemigrations evidence --name initial

# 3. Journeys (depends on users) - WITHOUT the load_journeys step
uv run python manage.py makemigrations journeys --name initial

# 4. LLMChat (depends on users, journeys)
uv run python manage.py makemigrations llmchat --name initial

# 5. Memory (depends on journeys, llmchat)
uv run python manage.py makemigrations memory --name initial
```

---

## Phase 4: Create Custom RunPython Migrations

Now manually create the custom migrations:

### 4.1 Create llmchat/0002_setup_langgraph_checkpointer.py

```powershell
uv run python manage.py makemigrations llmchat --empty --name setup_langgraph_checkpointer
```

Then edit the file to add the RunPython code from Phase 1.1.

### 4.2 Create memory/0002_setup_langgraph_store.py

```powershell
uv run python manage.py makemigrations memory --empty --name setup_langgraph_store
```

Then edit the file to add the RunPython code from Phase 1.2.

### 4.3 Create journeys/0002_load_journeys.py

```powershell
uv run python manage.py makemigrations journeys --empty --name load_journeys
```

Then edit the file to add the RunPython code from Phase 1.3.

**Important:** This migration must depend on `memory.0001_initial` because `load_journeys` creates ConversationPoint records.

---

## Phase 5: Verify Migration Dependencies

Check each migration file and ensure dependencies are correct:

### Expected Final Structure

```
users/migrations/
├── __init__.py
└── 0001_initial.py

llmchat/migrations/
├── __init__.py
├── 0001_initial.py                        # Schema only
└── 0002_setup_langgraph_checkpointer.py   # RunPython

journeys/migrations/
├── __init__.py
├── 0001_initial.py                        # Schema only
└── 0002_load_journeys.py                  # RunPython (depends on memory.0001)

memory/migrations/
├── __init__.py
├── 0001_initial.py                        # Schema only
└── 0002_setup_langgraph_store.py          # RunPython

evidence/migrations/
├── __init__.py
└── 0001_initial.py                        # Schema only (all final fields)
```

### Dependency Graph

```
users.0001_initial
    ↓
    ├── llmchat.0001_initial
    │       ↓
    │       └── llmchat.0002_setup_langgraph_checkpointer
    │
    ├── journeys.0001_initial
    │       ↓
    │       └── journeys.0002_load_journeys (also depends on memory.0001)
    │
    ├── memory.0001_initial (depends on journeys.0001, llmchat.0001)
    │       ↓
    │       └── memory.0002_setup_langgraph_store
    │
    └── evidence.0001_initial
```

---

## Phase 6: Test on Fresh Database

```powershell
# Drop and recreate local database (DESTRUCTIVE!)
# Option A: Using psql
psql -U postgres -c "DROP DATABASE IF EXISTS sdm_platform;"
psql -U postgres -c "CREATE DATABASE sdm_platform;"

# Option B: Using Django (if you have a reset command)
# uv run python manage.py reset_db --noinput

# Run all migrations
uv run python manage.py migrate

# Verify everything worked
uv run python manage.py showmigrations

# Run tests
uv run python manage.py test --keepdb
```

---

## Phase 7: Deploy to Production

Once local testing passes:

1. **Commit** all new migration files
2. **Push** to your deployment branch
3. **Reset** production database (since no data to preserve)
4. **Deploy** the new code
5. **Run migrations** on production:
   ```bash
   python manage.py migrate
   ```
6. **Verify** with `showmigrations`

---

## Rollback Plan

If something goes wrong:

1. **Don't panic** - since this is pre-launch, you can always reset again
2. **Check logs** for specific migration errors
3. **Common issues:**
   - Missing dependencies: Update the `dependencies` list in the migration
   - LangGraph setup fails: Check DATABASE_URL is set correctly
   - load_journeys fails: Ensure fixture files exist in `journeys/fixtures/`

---

## Verification Checklist

After migration squashing is complete, verify:

- [ ] `showmigrations` shows all migrations as applied
- [ ] Can create a new user via admin
- [ ] Can go through journey onboarding flow
- [ ] Conversation is created with LangChain history working
- [ ] Conversation points are loaded and displayed
- [ ] Memory extraction works (chat and check point status updates)
- [ ] Can delete a conversation (cascades properly)
- [ ] Can delete a user (cascades properly)
- [ ] All tests pass
