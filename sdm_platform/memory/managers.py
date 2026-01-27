# ruff: noqa: UP045
"""Memory management logic for user profiles and other memory types."""

import logging
from collections.abc import Callable
from datetime import UTC
from datetime import datetime
from functools import wraps
from typing import Optional

from langgraph.store.base import BaseStore
from pydantic import ValidationError

from sdm_platform.memory.schemas import ConversationPointMemory
from sdm_platform.memory.schemas import UserProfileMemory
from sdm_platform.memory.store import get_memory_store
from sdm_platform.memory.store import get_user_namespace

logger = logging.getLogger(__name__)


def with_store[T, **P](func: Callable[P, T]) -> Callable[P, T]:
    """
    Decorator that handles store context management.

    If a store is provided, uses it directly. Otherwise, creates a new store
    using the context manager. This eliminates the repeated pattern of:

        if store:
            return _inner(store)
        with get_memory_store() as s:
            return _inner(s)

    The decorated function must accept 'store' as a keyword argument.
    """

    @wraps(func)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
        store = kwargs.get("store")
        if store:
            return func(*args, **kwargs)
        with get_memory_store() as s:
            kwargs["store"] = s
            return func(*args, **kwargs)

    return wrapper


class UserProfileManager:
    """
    Manages user profile memory with single-document update pattern.

    Follows LangMem's enable_inserts=False approach: one profile per user,
    updated in-place with merge semantics (only non-None values overwrite).
    """

    PROFILE_KEY = "profile"

    @classmethod
    @with_store
    def get_profile(
        cls,
        user_id: str,
        store: Optional[BaseStore] = None,
    ) -> Optional[UserProfileMemory]:
        """
        Retrieve user profile from store.

        Args:
            user_id: User identifier (typically email)
            store: Optional store instance (uses context manager if not provided)

        Returns:
            UserProfileMemory if found, None otherwise
        """
        namespace = get_user_namespace(user_id, "profile")
        result = store.get(namespace, cls.PROFILE_KEY)  # type: ignore[union-attr]
        if result:
            return UserProfileMemory(**result.value)
        return None

    @classmethod
    @with_store
    def update_profile(
        cls,
        user_id: str,
        updates: dict,
        store: Optional[BaseStore] = None,
        source: str = "llm_extraction",
    ) -> UserProfileMemory:
        """
        Update user profile by merging with existing data.

        Only non-None values in updates will overwrite existing values.
        This preserves previously learned information.

        Args:
            user_id: User identifier (typically email)
            updates: Dictionary of fields to update
            store: Optional store instance
            source: Source of the update (llm_extraction, user_input, system)

        Returns:
            Updated UserProfileMemory
        """
        namespace = get_user_namespace(user_id, "profile")

        # Get existing profile or start fresh
        existing = store.get(namespace, cls.PROFILE_KEY)  # type: ignore[union-attr]
        current_data = dict(existing.value) if existing else {}

        # Merge updates (only non-None values)
        for key, value in updates.items():
            if value is not None:
                current_data[key] = value

        # Update metadata
        current_data["updated_at"] = datetime.now(UTC).isoformat()
        current_data["source"] = source

        # Validate through Pydantic
        profile = UserProfileMemory(**current_data)

        # Store in LangGraph store
        store.put(namespace, cls.PROFILE_KEY, profile.model_dump(mode="json"))  # type: ignore[union-attr]

        logger.info("Updated profile for %s: %s", user_id, list(updates.keys()))

        return profile

    @classmethod
    def format_for_prompt(cls, profile: Optional[UserProfileMemory]) -> str:
        """
        Format profile for inclusion in system prompt.

        Returns a human-readable summary of known user information
        that can be prepended to the system prompt.

        Args:
            profile: User profile or None

        Returns:
            Formatted string for system prompt, or empty string if no profile
        """
        if not profile:
            return ""

        parts = []

        if profile.preferred_name:
            parts.append(f"The user prefers to be called {profile.preferred_name}.")
        elif profile.name:
            parts.append(f"The user's name is {profile.name}.")

        if profile.birthday:
            parts.append(f"Their birthday is {profile.birthday.strftime('%B %d')}.")

        if not parts:
            return ""

        return "USER CONTEXT:\n" + " ".join(parts)


class ConversationPointManager:
    """
    Manages conversation point semantic memories in LangGraph store.
    """

    @classmethod
    @with_store
    def get_point_memory(
        cls,
        user_id: str,
        journey_slug: str,
        point_slug: str,
        store: Optional[BaseStore] = None,
    ) -> Optional["ConversationPointMemory"]:
        """
        Retrieve semantic memory for a specific conversation point.

        Args:
            user_id: User identifier
            journey_slug: Journey slug (e.g., "backpain")
            point_slug: Conversation point slug (e.g., "treatment-goals")
            store: Optional store instance

        Returns:
            ConversationPointMemory if found, None otherwise
        """
        namespace = get_user_namespace(
            user_id,
            "conversation_points",
            journey_slug=journey_slug,
        )
        key = f"point_{point_slug}"
        result = store.get(namespace, key)  # type: ignore[union-attr]
        if result:
            return ConversationPointMemory(**result.value)
        return None

    @classmethod
    @with_store
    def update_point_memory(
        cls,
        user_id: str,
        journey_slug: str,
        point_slug: str,
        updates: dict,
        store: Optional[BaseStore] = None,
    ) -> "ConversationPointMemory":
        """
        Update semantic memory for a conversation point.

        Args:
            user_id: User identifier
            journey_slug: Journey slug
            point_slug: Conversation point slug
            updates: Dictionary of fields to update
            store: Optional store instance

        Returns:
            Updated ConversationPointMemory
        """
        namespace = get_user_namespace(
            user_id,
            "conversation_points",
            journey_slug=journey_slug,
        )
        key = f"point_{point_slug}"

        # Get existing or create new
        existing = store.get(namespace, key)  # type: ignore[union-attr]
        current_data = (
            dict(existing.value)
            if existing
            else {
                "conversation_point_slug": point_slug,
                "journey_slug": journey_slug,
            }
        )

        # Merge updates (only non-None values)
        for k, v in updates.items():
            if v is not None:
                current_data[k] = v

        # Update timestamp
        current_data["last_analyzed_at"] = datetime.now(UTC).isoformat()

        # Validate
        memory = ConversationPointMemory(**current_data)  # pyright: ignore[reportArgumentType]

        # Store
        store.put(namespace, key, memory.model_dump(mode="json"))  # type: ignore[union-attr]

        logger.info(
            "Updated conversation point memory for %s/%s/%s",
            user_id,
            journey_slug,
            point_slug,
        )

        return memory

    @classmethod
    @with_store
    def get_all_point_memories(
        cls,
        user_id: str,
        journey_slug: str,
        store: Optional[BaseStore] = None,
    ) -> list["ConversationPointMemory"]:
        """
        Get all conversation point memories for a journey.

        Args:
            user_id: User identifier
            journey_slug: Journey slug
            store: Optional store instance

        Returns:
            List of ConversationPointMemory objects
        """
        namespace = get_user_namespace(
            user_id,
            "conversation_points",
            journey_slug=journey_slug,
        )

        # Search for all items with point_ prefix
        results = store.search(namespace)  # type: ignore[union-attr]
        memories = []
        for item in results:
            if item.key.startswith("point_"):
                try:
                    memories.append(ConversationPointMemory(**item.value))
                except (ValidationError, TypeError, KeyError) as e:
                    logger.warning(
                        "Failed to parse memory for key %s: %s",
                        item.key,
                        e,
                    )
        return memories

    @classmethod
    def mark_as_initiated(
        cls,
        user_id: str,
        journey_slug: str,
        point_slug: str,
        store: Optional[BaseStore] = None,
    ) -> "ConversationPointMemory":
        """
        Mark a conversation point as manually initiated by the user.

        Called when user clicks a conversation point in the UI.

        Args:
            user_id: User identifier
            journey_slug: Journey slug
            point_slug: Conversation point slug
            store: Optional store instance

        Returns:
            Updated ConversationPointMemory
        """
        return cls.update_point_memory(
            user_id=user_id,
            journey_slug=journey_slug,
            point_slug=point_slug,
            updates={
                "manually_initiated": True,
                "initiated_at": datetime.now(UTC).isoformat(),
            },
            store=store,
        )
