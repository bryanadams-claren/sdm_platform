import logging
import uuid

from django.db import models
from django.db import transaction
from django.db.models import Q
from django.db.models.signals import post_delete
from django.db.models.signals import post_save
from django.dispatch import receiver
from psycopg import DatabaseError
from psycopg import InterfaceError
from psycopg import OperationalError

from sdm_platform.llmchat.tasks import ensure_initial_message_in_langchain
from sdm_platform.llmchat.utils.format import format_thread_id
from sdm_platform.llmchat.utils.graph import get_postgres_checkpointer
from sdm_platform.users.models import User

logger = logging.getLogger(__name__)


class ConversationTemplate(models.Model):
    """
    Defines a 'default' conversation type from which user conversations can be seeded.
    Example slugs: 'symptom-qa', 'treatment-options'
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    slug = models.SlugField(max_length=100, unique=True)  # stable identifier
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True, default="")

    # Default payloads used when creating a user conversation
    default_system_prompt = models.TextField(blank=True, default="")
    default_model_name = models.CharField(max_length=100, default="gpt-4")

    # Optional: have the assistant post the first message in the seeded conversation
    initial_message = models.TextField(blank=True, default="")

    # Controls visibility/creation of seed conversations
    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveIntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["sort_order", "slug"]

    def __str__(self):
        return f"ConversationTemplate: {self.slug}"

    def ensure_for_user(self, user):
        """
        Idempotently ensure the user has one seed conversation for this template.
        Returns (conversation, created: bool).
        """
        from .models import Conversation  # noqa: I001, PLC0415 # local import to avoid circulars

        with transaction.atomic():
            convo = (
                Conversation.objects.select_for_update()
                .filter(user=user, template=self, is_seed=True)
                .first()
            )
            if convo:
                return convo, False

            conv_id = f"{self.slug}-seed"
            # Create a new seed conversation
            convo = Conversation.objects.create(
                conv_id=conv_id,
                user=user,
                title=self.title,
                thread_id=format_thread_id(user, conv_id),
                is_active=True,
                system_prompt=self.default_system_prompt,
                model_name=self.default_model_name or "gpt-4",
                template=self,
                is_seed=True,
            )
            ensure_initial_message_in_langchain.delay(convo.id)  # pyright: ignore[reportCallIssue]

            return convo, True


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

    # Link back to the default conversation template (optional)
    template = models.ForeignKey(
        ConversationTemplate,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="conversations",
    )

    # Marks the auto-created seed conversation for a template
    is_seed = models.BooleanField(default=False, db_index=True)

    class Meta:
        constraints = [
            # Ensure at most one seed conversation per (user, template)
            models.UniqueConstraint(
                fields=["user", "template"],
                condition=Q(is_seed=True) & Q(template__isnull=False),
                name="unique_seed_conversation_per_template_per_user",
            ),
        ]

    def __str__(self):
        return f"Conversation: {self.user.username} / {self.title} ({self.id})"


def ensure_default_conversations(user):
    """
    Idempotently ensure the user has at least one seed conversation for each active
    template. Safe to call multiple times (e.g., on signup and/or first chat visit).
    """
    templates = ConversationTemplate.objects.filter(is_active=True).order_by(
        "sort_order",
        "slug",
    )
    created_any = False
    for tpl in templates:
        _, created = tpl.ensure_for_user(user)
        created_any = created_any or created
    return created_any


@receiver(post_save, sender=User)
def create_seed_conversations_for_new_user(sender, instance, created, **kwargs):
    """
    When a new user is created, ensure they get one seed conversation for
    each active template.
    """
    if not created:
        return
    transaction.on_commit(lambda: ensure_default_conversations(instance))
    logger.info("Created seed conversations for new user %s", instance.username)


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
