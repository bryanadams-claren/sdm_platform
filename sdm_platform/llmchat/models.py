import logging
import uuid

from django.db import models
from django.db.models.signals import post_delete
from django.dispatch import receiver
from psycopg import DatabaseError
from psycopg import InterfaceError
from psycopg import OperationalError

from sdm_platform.llmchat.utils.graph import get_postgres_checkpointer
from sdm_platform.users.models import User

logger = logging.getLogger(__name__)


class Conversation(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    conv_id = models.CharField(max_length=255)
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="conversations",
    )

    # A human-friendly title (optional, for UI)
    title = models.CharField(max_length=255, default="")

    # LangChain / checkpointing identifiers
    thread_id = models.CharField(max_length=255, unique=True)
    # This ties to LangChain's memory/checkpoint backend

    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_active = models.BooleanField(
        default=True,
    )  # Useful for marking archived/finished chats

    # Optional context
    system_prompt = models.TextField(blank=True, default="")  # initial instructions
    model_name = models.CharField(max_length=100, default="gpt-4")  # which LLM used

    def __str__(self):
        return f"Conversation: {self.user.username} / {self.title} ({self.id})"


@receiver(post_delete, sender=Conversation)
def delete_langchain_history_on_conversation_delete(
    sender,
    instance: Conversation,
    **kwargs,
):
    """
    When a Conversation is deleted, also delete its LangChain/graph history
    from the Postgres checkpointer using the conversation's thread_id.
    """
    thread_id = getattr(instance, "thread_id", None)
    if not thread_id:
        logger.error(
            "Could not find thread_id in %s to delete LangChain history",
            instance,
        )
        return

    try:
        with get_postgres_checkpointer() as checkpointer:
            checkpointer.delete_thread(thread_id)
            logger.info("Deleted LangChain history for thread_id=%s", thread_id)

    except (
        OperationalError,
        DatabaseError,
        InterfaceError,
        ConnectionError,
        TimeoutError,
    ):
        # Don't block the ORM delete; just log.
        logger.exception(
            "Failed to delete LangChain history for thread_id=%s",
            thread_id,
        )
