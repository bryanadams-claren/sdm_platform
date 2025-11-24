#!/usr/bin/env python
"""Django's command-line utility for administrative tasks."""

import sys
from pathlib import Path


def main():
    """Run administrative tasks."""
    # Setup environment before importing Django
    from config.env_setup import setup_django_environment  # noqa: PLC0415

    setup_django_environment()

    try:
        from django.core.management import execute_from_command_line  # noqa: PLC0415
    except ImportError as exc:
        raise ImportError(  # noqa: TRY003
            "Couldn't import Django. Are you sure it's installed and "  # noqa: EM101
            "available on your PYTHONPATH environment variable? Did you "
            "forget to activate a virtual environment?",
        ) from exc

    # This allows easy placement of apps within the interior
    # sdm_platform directory.
    current_path = Path(__file__).parent.resolve()
    sys.path.append(str(current_path / "sdm_platform"))

    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
