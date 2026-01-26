import logging
import uuid
from typing import TYPE_CHECKING

from django.db import models
from django.db.models.signals import post_delete
from django.dispatch import receiver
from psycopg import DatabaseError
from psycopg import InterfaceError
from psycopg import OperationalError

from sdm_platform.llmchat.utils.graphs import get_postgres_checkpointer
from sdm_platform.users.models import User

if TYPE_CHECKING:
    from sdm_platform.journeys.models import JourneyResponse
    from sdm_platform.memory.models import ConversationSummary

logger = logging.getLogger(__name__)


class Conversation(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="conversations",
    )

    # Link to the journey this conversation belongs to
    journey = models.ForeignKey(
        "journeys.Journey",
        on_delete=models.CASCADE,
        related_name="conversations",
        null=True,  # Nullable for migration; can make required later
        blank=True,
        help_text="The journey/condition this conversation is associated with",
    )

    # A human-friendly title (optional, for UI)
    title = models.CharField(max_length=255, default="")

    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_active = models.BooleanField(
        default=True,
    )  # Useful for marking archived/finished chats

    # Optional context
    system_prompt = models.TextField(blank=True, default="")  # initial instructions

    # Analytics fields for reporting
    message_count = models.PositiveIntegerField(
        default=0,
        help_text="Number of messages in this conversation",
    )
    last_message_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Timestamp of the most recent message",
    )

    if TYPE_CHECKING:
        # Reverse OneToOne relationships for type checkers
        summary: "ConversationSummary"
        journey_response: "JourneyResponse"

    def __str__(self):
        return f"Conversation: {self.user.email} / {self.title} ({self.id})"

    @property
    def thread_id(self) -> str:
        """
        Return the thread_id used for LangChain checkpointer.

        This is simply the string representation of the UUID primary key.
        """
        return str(self.id)


@receiver(post_delete, sender=Conversation)
def delete_langchain_history_on_conversation_delete(
    sender,
    instance: Conversation,
    **kwargs,
):
    """
    When a Conversation is deleted, also delete its LangChain/graph history
    from the Postgres checkpointer using the conversation's id as thread_id.
    """
    thread_id = str(instance.id)

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


@receiver(post_delete, sender=Conversation)
def delete_memory_store_on_conversation_delete(
    sender,
    instance: Conversation,
    **kwargs,
):
    """
    When a Conversation is deleted, also delete the associated memory store data.

    This cleans up journey-specific memories (conversation points, etc.)
    for this user/journey combination.
    """
    # Only delete if conversation had a journey
    if not instance.journey:
        return

    user_email = instance.user.email
    journey_slug = instance.journey.slug

    try:
        from sdm_platform.memory.store import delete_user_memories  # noqa: PLC0415

        # Only delete journey-specific memories, not profile/insights
        deleted_count = delete_user_memories(user_email, [journey_slug])
        logger.info(
            "Deleted %d memory items for conversation %s (user=%s, journey=%s)",
            deleted_count,
            instance.id,
            user_email,
            journey_slug,
        )
    except Exception:
        # Don't block the ORM delete; just log.
        logger.exception(
            "Failed to delete memory store data for conversation %s",
            instance.id,
        )
