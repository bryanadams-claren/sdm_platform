import logging

from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _

logger = logging.getLogger(__name__)


class LlmchatConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "sdm_platform.llmchat"
    verbose_name = _("LLM Chat")

    def ready(self):
        # PostgresSaver checkpoints table is now initialized via migration
        # (see migrations/0002_setup_langgraph_checkpointer.py)
        # This prevents issues with apps.ready() being called before migrations run
        pass
