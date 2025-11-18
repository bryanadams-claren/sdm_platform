import logging
import os

from django.apps import AppConfig

from sdm_platform.llmchat.utils.graph import get_postgres_checkpointer

logger = logging.getLogger(__name__)


class LlmchatConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "sdm_platform.llmchat"

    def ready(self):
        if os.getenv("DJANGO_SKIP_DB_INIT") != "1":
            with get_postgres_checkpointer() as checkpointer:
                checkpointer.setup()
            logger.info("PostGreSQL checkpointer initialized.")
