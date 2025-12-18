# ruff: noqa: UP045, ERA001
# UP045 -- | None on typing
# ERA0001 -- Keeping some code for next memory
#
"""Pydantic schemas for memory types."""

from datetime import UTC
from datetime import date
from datetime import datetime
from typing import Literal
from typing import Optional

from pydantic import BaseModel
from pydantic import Field


def _utc_now() -> datetime:
    """Return current UTC time (timezone-aware)."""
    return datetime.now(UTC)


class UserProfileMemory(BaseModel):
    """
    User profile memory - single document per user.

    Stores demographic and preference information learned from conversations.
    Uses merge-update pattern: only non-None values overwrite existing data.
    """

    # Core identity
    name: Optional[str] = Field(default=None, description="User's full name")
    preferred_name: Optional[str] = Field(
        default=None,
        description="How the user prefers to be addressed",
    )
    birthday: Optional[date] = Field(default=None, description="User's birthday")

    # Metadata
    updated_at: datetime = Field(default_factory=_utc_now)
    source: Literal["user_input", "llm_extraction", "system"] = Field(
        default="llm_extraction",
        description="How this information was obtained",
    )

    class Config:
        json_schema_extra = {
            "example": {
                "name": "Jane Doe",
                "preferred_name": "Jane",
                "birthday": "1985-03-15",
            },
        }


# Future memory types can be added here:
#
# class JourneyMemory(BaseModel):
#     """Journey-specific memory - one per user per journey."""
#     journey_slug: str
#     stated_preferences: list[str] = Field(default_factory=list)
#     concerns: list[str] = Field(default_factory=list)
#     values: list[str] = Field(default_factory=list)
#     ...
