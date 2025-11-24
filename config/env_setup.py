"""
Environment setup for SDM Platform.

This module handles loading .env files and setting the appropriate Django settings
module.  It should be imported at the top of all entry points (manage.py, wsgi.py,
asgi.py, celery_app.py).
"""

import os
from pathlib import Path


def setup_django_environment():
    """Load .env file and set DJANGO_SETTINGS_MODULE if not already set."""
    # Get the base directory (project root)
    BASE_DIR = Path(__file__).resolve().parent.parent  # noqa: N806

    # Load .env file if it exists (for local development)
    env_file = BASE_DIR / ".env"
    if env_file.exists():
        with Path.open(env_file) as f:
            for raw_line in f:
                line = raw_line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    # Only set if not already in environment
                    os.environ.setdefault(key, value)

    # Set default Django settings module (production is the safe default)
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.production")
