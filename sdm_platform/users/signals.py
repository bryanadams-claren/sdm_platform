"""Signals for user model events."""

import logging

from django.db.models.signals import pre_delete
from django.dispatch import receiver

from sdm_platform.users.models import User

logger = logging.getLogger(__name__)


@receiver(pre_delete, sender=User)
def delete_user_memory_store_data(sender, instance: User, **kwargs):
    """
    Delete all memory store data for a user before they are deleted.

    This cleans up:
    - User profile memory
    - User insights
    - Journey-specific memories (conversation points, etc.)

    Uses pre_delete to access journey_responses before they're cascade deleted.
    """
    from sdm_platform.memory.store import delete_user_memories  # noqa: PLC0415

    user_email = instance.email

    # Get all journey slugs the user participated in (before cascade delete)
    journey_slugs = list(
        instance.journey_responses.values_list("journey__slug", flat=True)
    )

    logger.info(
        "Deleting memory store data for user %s (journeys: %s)",
        user_email,
        journey_slugs,
    )

    try:
        deleted_count = delete_user_memories(user_email, journey_slugs)
        logger.info(
            "Deleted %d memory items for user %s",
            deleted_count,
            user_email,
        )
    except Exception:
        # Log but don't block user deletion
        logger.exception(
            "Failed to delete memory store data for user %s",
            user_email,
        )
