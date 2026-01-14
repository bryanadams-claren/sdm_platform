"""Context loading node - loads user profile and system prompt."""

import logging

from langchain_core.runnables import RunnableConfig
from langgraph.store.base import BaseStore

from sdm_platform.llmchat.utils.graphs.base import SdmState
from sdm_platform.memory.managers import UserProfileManager

logger = logging.getLogger(__name__)


def create_load_context_node(store: BaseStore | None = None):
    """
    Factory function to create load_context node with store binding.

    Args:
        store: PostgresStore for memory lookup

    Returns:
        Node function that loads user context and system prompt
    """

    def load_context(state: SdmState, config: RunnableConfig):
        """
        Load all context needed for the conversation:
        - User profile from memory store (name, preferences, etc.)
        - Conversation system prompt (journey responses, etc.)

        This runs at the start of each turn to provide full context.
        """
        user_context = ""
        system_prompt = ""

        # Load user profile from memory store
        if store:
            user_id = config.get("configurable", {}).get("user_id")
            if user_id:
                try:
                    profile = UserProfileManager.get_profile(user_id, store=store)
                    user_context = UserProfileManager.format_for_prompt(profile)
                except Exception:
                    logger.exception("Error loading user context for %s", user_id)

        # Load conversation system prompt (from state if provided)
        # This comes from the initial invoke call in tasks.py
        system_prompt = state.get("system_prompt", "")

        return {
            "user_context": user_context,
            "system_prompt": system_prompt,
        }

    return load_context
