# ruff: noqa: E402
"""
ASGI config for SDM Platform project.

It exposes the ASGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/dev/howto/deployment/asgi/

"""

import sys
from pathlib import Path

# Setup environment before importing Django
from config.env_setup import setup_django_environment

setup_django_environment()

# This application object is used by any ASGI server configured to use this file.
# This has to be imported before the channels stuff, otherwise an "Apps aren't
#   loaded yet" error occurs
from django.core.asgi import get_asgi_application

django_application = get_asgi_application()

from channels.auth import AuthMiddlewareStack
from channels.routing import ProtocolTypeRouter
from channels.routing import URLRouter
from channels.security.websocket import AllowedHostsOriginValidator

import config.routing

# This allows easy placement of apps within the interior
# sdm_platform directory.
BASE_DIR = Path(__file__).resolve(strict=True).parent.parent
sys.path.append(str(BASE_DIR / "sdm_platform"))

application = ProtocolTypeRouter(
    {
        "http": django_application,
        "websocket": AllowedHostsOriginValidator(
            AuthMiddlewareStack(
                URLRouter(
                    config.routing.websocket_urlpatterns,
                ),
            ),
        ),
    },
)
