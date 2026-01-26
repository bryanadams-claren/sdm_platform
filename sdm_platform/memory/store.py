# ruff: noqa: UP043
"""PostgresStore initialization and helpers for memory management."""

import hashlib
from collections.abc import Generator
from contextlib import contextmanager
from logging import getLogger

import environ
from langgraph.store.postgres import PostgresStore

env = environ.Env()
logger = getLogger(__name__)

# Memory types that need to be cleaned up when a user is deleted
MEMORY_TYPES = ["profile", "insights"]
JOURNEY_MEMORY_TYPES = ["journey", "conversation_points"]


@contextmanager
def get_memory_store() -> Generator[PostgresStore, None, None]:
    """
    Context manager for PostgresStore access.

    Uses the same DATABASE_URL as the checkpointer for consistency.

    Usage:
        with get_memory_store() as store:
            store.put(namespace, key, value)
            result = store.get(namespace, key)
    """
    conn_string = env.str("DATABASE_URL")
    if not str(conn_string):
        errmsg = f"DATABASE_URL not set: {conn_string}"
        logger.exception(errmsg)
        raise ValueError(errmsg)
    with PostgresStore.from_conn_string(str(conn_string)) as store:
        yield store


def _encode_user_id(user_id: str) -> str:
    """
    Encode user_id for use in namespace.

    PostgresStore namespaces cannot contain periods, but email addresses do.
    We create a short hash of the email for the namespace.

    Args:
        user_id: User identifier (typically email with periods)

    Returns:
        Hash-encoded identifier safe for namespace use
    """
    # Use first 16 chars of SHA256 hash for a reasonable namespace identifier
    return hashlib.sha256(user_id.encode()).hexdigest()[:16]


def get_user_namespace(
    user_id: str, memory_type: str, **kwargs: str
) -> tuple[str, ...]:
    """
        Build namespace tuple for a given memory type.

        Args:
            user_id: User identifier (typically email)
            memory_type: One of 'profile', 'journey', 'insights', 'conversation_points'
            **kwargs: Additional namespace components (e.g., journey_slug)

        Returns:
            Tuple namespace for use with store.get/put/search

        Examples:
    >>> get_user_namespace("user@ex.com", "profile")
    ("memory", "users", "a1b2c3d4e5f6g7h8", "profile")

    >>> get_user_namespace("user@ex.com", "journey", journey_slug="backpain")
    ("memory", "users", "a1b2c3d4e5f6g7h8", "journeys", "backpain")

    >>> get_user_namespace("user@ex.com","conversation_points",journey_slug="backpain")
    ("memory", "users", "a1b2c3d4e5f6g7h8", "conversation_points", "backpain")
    """
    # Encode user_id to avoid periods in namespace
    encoded_user_id = _encode_user_id(user_id)

    namespaces: dict[str, tuple[str, ...]] = {
        "profile": ("memory", "users", encoded_user_id, "profile"),
        "journey": (
            "memory",
            "users",
            encoded_user_id,
            "journeys",
            kwargs.get("journey_slug", ""),
        ),
        "insights": ("memory", "users", encoded_user_id, "insights"),
        "conversation_points": (
            "memory",
            "users",
            encoded_user_id,
            "conversation_points",
            kwargs.get("journey_slug", ""),
        ),
    }
    return namespaces.get(
        memory_type, ("memory", "users", encoded_user_id, memory_type)
    )


def delete_user_memories(user_id: str, journey_slugs: list[str] | None = None) -> int:
    """
    Delete all memory store data for a user.

    Args:
        user_id: User identifier (typically email)
        journey_slugs: List of journey slugs the user participated in.
                       If None, only non-journey memories are deleted.

    Returns:
        Number of items deleted
    """
    deleted_count = 0
    encoded_user_id = _encode_user_id(user_id)

    with get_memory_store() as store:
        # Delete non-journey memories (profile, insights)
        for memory_type in MEMORY_TYPES:
            namespace = get_user_namespace(user_id, memory_type)
            try:
                items = list(store.search(namespace))
                for item in items:
                    store.delete(namespace, item.key)
                    deleted_count += 1
                logger.info(
                    "Deleted %d %s memories for user %s",
                    len(items),
                    memory_type,
                    encoded_user_id,
                )
            except Exception:
                logger.exception(
                    "Error deleting %s memories for user %s",
                    memory_type,
                    encoded_user_id,
                )

        # Delete journey-specific memories
        if journey_slugs:
            for journey_slug in journey_slugs:
                for memory_type in JOURNEY_MEMORY_TYPES:
                    namespace = get_user_namespace(
                        user_id, memory_type, journey_slug=journey_slug
                    )
                    try:
                        items = list(store.search(namespace))
                        for item in items:
                            store.delete(namespace, item.key)
                            deleted_count += 1
                        logger.info(
                            "Deleted %d %s memories for user %s, journey %s",
                            len(items),
                            memory_type,
                            encoded_user_id,
                            journey_slug,
                        )
                    except Exception:
                        logger.exception(
                            "Error deleting %s memories for user %s, journey %s",
                            memory_type,
                            encoded_user_id,
                            journey_slug,
                        )

    logger.info(
        "Total memories deleted for user %s: %d",
        encoded_user_id,
        deleted_count,
    )
    return deleted_count
