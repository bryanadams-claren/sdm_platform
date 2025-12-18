# ruff: noqa: UP045
"""Memory management logic for user profiles and other memory types."""

import logging
from datetime import UTC
from datetime import datetime
from typing import Optional

from langgraph.store.base import BaseStore

from sdm_platform.memory.schemas import UserProfileMemory
from sdm_platform.memory.store import get_memory_store
from sdm_platform.memory.store import get_user_namespace

logger = logging.getLogger(__name__)


class UserProfileManager:
    """
    Manages user profile memory with single-document update pattern.

    Follows LangMem's enable_inserts=False approach: one profile per user,
    updated in-place with merge semantics (only non-None values overwrite).
    """

    PROFILE_KEY = "profile"

    @classmethod
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

        def _get(s: BaseStore) -> Optional[UserProfileMemory]:
            result = s.get(namespace, cls.PROFILE_KEY)
            if result:
                return UserProfileMemory(**result.value)
            return None

        if store:
            return _get(store)

        with get_memory_store() as s:
            return _get(s)

    @classmethod
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

        def _do_update(s: BaseStore) -> UserProfileMemory:
            # Get existing profile or start fresh
            existing = s.get(namespace, cls.PROFILE_KEY)
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
            s.put(namespace, cls.PROFILE_KEY, profile.model_dump(mode="json"))

            logger.info("Updated profile for %s: %s", user_id, list(updates.keys()))

            return profile

        if store:
            return _do_update(store)

        with get_memory_store() as s:
            return _do_update(s)

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
