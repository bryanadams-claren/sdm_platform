"""Service for aggregating conversation summary data."""

import logging
from datetime import UTC
from datetime import datetime

from sdm_platform.journeys.models import JourneyResponse
from sdm_platform.llmchat.models import Conversation
from sdm_platform.memory.managers import ConversationPointManager
from sdm_platform.memory.managers import UserProfileManager
from sdm_platform.memory.models import ConversationPoint
from sdm_platform.memory.schemas import ConversationSummaryData
from sdm_platform.memory.schemas import JourneyOptionSummary
from sdm_platform.memory.schemas import PointSummary

logger = logging.getLogger(__name__)


class ConversationSummaryService:
    """Aggregates conversation data and checks completion status."""

    def __init__(self, conversation: Conversation):
        """
        Initialize the summary service.

        Args:
            conversation: The conversation to summarize
        """
        self.conversation = conversation
        self.journey = conversation.journey
        self.user = conversation.user

        if not self.journey:
            msg = "Cannot create summary for conversation without a journey"
            raise ValueError(msg)

    def is_complete(self) -> bool:
        """
        Check if ALL conversation points are addressed.

        Returns:
            True if all conversation points have is_addressed=True
        """
        if not self.journey:
            return False

        # Get all active conversation points for this journey
        conversation_points = ConversationPoint.objects.filter(
            journey=self.journey, is_active=True
        )

        if not conversation_points.exists():
            return False

        # Get all point memories from LangGraph store
        point_memories = ConversationPointManager.get_all_point_memories(
            user_id=self.user.email,
            journey_slug=self.journey.slug,
        )

        # Create a lookup dict by slug
        memory_by_slug = {mem.conversation_point_slug: mem for mem in point_memories}

        # Check if every point is addressed
        for point in conversation_points:
            memory = memory_by_slug.get(point.slug)
            if not memory or not memory.is_addressed:
                return False

        return True

    def get_summary_data(self, narrative_summary: str = "") -> ConversationSummaryData:
        """
        Aggregate all data needed for PDF generation.

        Args:
            narrative_summary: LLM-generated narrative (set later if empty)

        Returns:
            ConversationSummaryData with all fields populated
        """
        # Get user profile
        user_profile = UserProfileManager.get_profile(user_id=self.user.email)
        user_name = (
            user_profile.name if user_profile and user_profile.name else self.user.name
        )
        preferred_name = user_profile.preferred_name if user_profile else None

        # Get onboarding responses
        onboarding_responses = {}
        try:
            journey_response = JourneyResponse.objects.get(
                user=self.user, journey=self.journey
            )
            onboarding_responses = journey_response.responses or {}
        except JourneyResponse.DoesNotExist:
            logger.warning(
                "No JourneyResponse found for user %s, journey %s",
                self.user.email,
                self.journey.slug,
            )

        # Get point summaries
        point_summaries = self.get_point_summaries()

        # Get selected option if any
        selected_option = None
        try:
            journey_response = JourneyResponse.objects.get(
                user=self.user, journey=self.journey
            )
            if journey_response.selected_option:
                opt = journey_response.selected_option
                selected_option = JourneyOptionSummary(
                    title=opt.title,
                    description=opt.description,
                    benefits=opt.benefits or [],
                    drawbacks=opt.drawbacks or [],
                    typical_timeline=opt.typical_timeline,
                )
        except JourneyResponse.DoesNotExist:
            pass

        return ConversationSummaryData(
            user_name=user_name,
            preferred_name=preferred_name,
            journey_title=self.journey.title,
            journey_description=self.journey.description,
            onboarding_responses=onboarding_responses,
            point_summaries=point_summaries,
            selected_option=selected_option,
            narrative_summary=narrative_summary,
            generated_at=datetime.now(UTC),
            conversation_id=str(self.conversation.id),
        )

    def get_point_summaries(self) -> list[PointSummary]:
        """
        Get summary data for each conversation point.

        Returns:
            List of PointSummary objects
        """
        # Get all active conversation points
        conversation_points = ConversationPoint.objects.filter(
            journey=self.journey, is_active=True
        ).order_by("sort_order")

        # Get all point memories
        point_memories = ConversationPointManager.get_all_point_memories(
            user_id=self.user.email,
            journey_slug=self.journey.slug,
        )

        # Create lookup dict
        memory_by_slug = {mem.conversation_point_slug: mem for mem in point_memories}

        # Build summaries
        summaries = []
        for point in conversation_points:
            memory = memory_by_slug.get(point.slug)

            # Parse first_addressed_at if it exists
            first_addressed_at: datetime | None = None
            if memory and memory.first_addressed_at:
                if isinstance(memory.first_addressed_at, str):
                    first_addressed_at = datetime.fromisoformat(
                        memory.first_addressed_at
                    )
                else:
                    first_addressed_at = memory.first_addressed_at

            summaries.append(
                PointSummary(
                    title=point.title,
                    description=point.description,
                    extracted_points=memory.extracted_points if memory else [],
                    relevant_quotes=memory.relevant_quotes if memory else [],
                    structured_data=memory.structured_data if memory else {},
                    first_addressed_at=first_addressed_at,
                )
            )

        return summaries
