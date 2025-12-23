# ruff: noqa: UP045
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


class ConversationPointMemory(BaseModel):
    """
    Semantic memory for a conversation point.

    This represents what was learned/discussed about a specific topic.
    Stored in LangGraph store for efficient semantic search.
    """

    conversation_point_slug: str = Field(description="Slug of the conversation point")

    journey_slug: str = Field(description="Slug of the journey this belongs to")

    # Semantic content
    is_addressed: bool = Field(
        default=False, description="Whether this topic has been sufficiently discussed"
    )

    confidence_score: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Confidence that this topic has been addressed",
    )

    extracted_points: list[str] = Field(
        default_factory=list, description="Key points extracted from the discussion"
    )

    relevant_quotes: list[str] = Field(
        default_factory=list, description="Relevant quotes from the user"
    )

    # Structured data extraction
    structured_data: dict = Field(
        default_factory=dict,
        description="Structured information extracted (e.g., goals, preferences)",
    )

    # Metadata
    first_addressed_at: Optional[datetime] = Field(
        default=None, description="When this was first discussed"
    )

    last_analyzed_at: datetime = Field(
        default_factory=_utc_now,
        description="Last time messages were analyzed for this point",
    )

    message_count_analyzed: int = Field(
        default=0, description="Number of messages analyzed for this extraction"
    )

    class Config:
        json_schema_extra = {
            "example": {
                "conversation_point_slug": "treatment-goals",
                "journey_slug": "backpain",
                "is_addressed": True,
                "confidence_score": 0.85,
                "extracted_points": [
                    "Wants to return to gardening",
                    "Goal is to walk without pain",
                    "Timeline: within 3 months",
                ],
                "relevant_quotes": [
                    "I really miss being able to garden",
                    "I'd love to walk around the block without hurting",
                ],
                "structured_data": {
                    "activities_missed": ["gardening", "walking"],
                    "timeline": "3 months",
                },
            }
        }
