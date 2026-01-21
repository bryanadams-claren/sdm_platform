"""Memory extraction node - spawns async Celery tasks for memory extraction."""

import logging

from langchain_core.runnables import RunnableConfig

from sdm_platform.llmchat.utils.graphs.base import SdmState
from sdm_platform.memory.tasks import extract_all_memories
from sdm_platform.memory.tasks import extract_user_profile_memory

logger = logging.getLogger(__name__)


def create_extract_memories_node():
    """
    Creates a node that spawns memory extraction as async Celery task.

    Non-blocking - fires task and returns immediately.
    This node runs after call_model to extract memories from the conversation.
    """

    def extract_memories(state: SdmState, config: RunnableConfig):
        """
        Extract memories from the conversation by spawning async Celery tasks.

        Gets user_id and journey_slug from config, formats recent messages,
        and fires the appropriate extraction task.

        Returns state unchanged (non-blocking).
        """
        configurable = config.get("configurable", {})
        user_id = configurable.get("user_id")
        journey_slug = configurable.get("journey_slug")

        if not user_id:
            logger.warning("extract_memories: no user_id in config, skipping")
            return state

        # Format recent messages for extraction (last 50)
        recent_messages = [
            {"role": m.type, "content": m.content}
            for m in state["messages"][-50:]
            if hasattr(m, "type") and hasattr(m, "content")
        ]

        if not recent_messages:
            logger.debug("extract_memories: no messages to extract from")
            return state

        # Get thread_id for WebSocket status updates
        thread_id = configurable.get("thread_id")

        # Fire async task (non-blocking)
        if journey_slug:
            logger.info(
                "Spawning extract_all_memories for user=%s, journey=%s",
                user_id,
                journey_slug,
            )
            extract_all_memories.delay(  # pyright: ignore[reportCallIssue]
                user_id, journey_slug, recent_messages, thread_id
            )
        else:
            logger.info("Spawning extract_user_profile_memory for user=%s", user_id)
            extract_user_profile_memory.delay(user_id, recent_messages)  # pyright: ignore[reportCallIssue]

        # Return state unchanged
        return state

    return extract_memories
