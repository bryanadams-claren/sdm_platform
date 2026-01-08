"""Views for memory app - conversation points API."""

import logging

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404

from sdm_platform.llmchat.models import Conversation
from sdm_platform.memory.managers import ConversationPointManager

logger = logging.getLogger(__name__)


@login_required
def conversation_points_api(request, conv_id):
    """
    API endpoint to get conversation points for a specific conversation.

    Returns conversation points with their completion status for the current user.

    Args:
        request: Django request object
        conv_id: Conversation ID

    Returns:
        JsonResponse with:
        {
            "success": true,
            "journey_slug": "backpain",
            "journey_title": "Back Pain Decision Support",
            "points": [
                {
                    "slug": "treatment-goals",
                    "title": "Discuss your goals for treatment",
                    "description": "...",
                    "sort_order": 0,
                    "is_addressed": true,
                    "confidence_score": 0.85,
                    "extracted_points": ["Wants to garden", "Walk without pain"],
                    "first_addressed_at": "2024-01-15T10:30:00Z"
                },
                ...
            ]
        }
    """
    try:
        # Get the conversation for this user
        conversation = get_object_or_404(
            Conversation,
            conv_id=conv_id,
            user=request.user,
        )

        # Check if conversation has a journey
        if not conversation.journey:
            return JsonResponse(
                {
                    "success": False,
                    "error": "No journey associated with this conversation",
                    "points": [],
                }
            )

        journey = conversation.journey

        # Get all active conversation points for this journey
        conversation_points = journey.conversation_points.filter(
            is_active=True
        ).order_by("sort_order", "slug")

        # Build response with completion status from memory store
        points_data = []
        user_id = request.user.email

        for point in conversation_points:
            # Get memory from LangGraph store
            point_memory = ConversationPointManager.get_point_memory(
                user_id=user_id,
                journey_slug=journey.slug,
                point_slug=point.slug,
            )

            # Build point data
            point_data = {
                "slug": point.slug,
                "title": point.title,
                "description": point.description,
                "sort_order": point.sort_order,
                "is_addressed": False,
                "confidence_score": 0.0,
                "extracted_points": [],
                "first_addressed_at": None,
            }

            # Merge memory data if it exists
            if point_memory:
                point_data.update(
                    {
                        "is_addressed": point_memory.is_addressed,
                        "confidence_score": point_memory.confidence_score,
                        "extracted_points": point_memory.extracted_points,
                        "first_addressed_at": (
                            point_memory.first_addressed_at.isoformat()
                            if point_memory.first_addressed_at
                            else None
                        ),
                    }
                )

            points_data.append(point_data)

        return JsonResponse(
            {
                "success": True,
                "journey_slug": journey.slug,
                "journey_title": journey.title,
                "points": points_data,
            }
        )

    except Exception as e:
        logger.exception("Error fetching conversation points for conv_id=%s", conv_id)
        return JsonResponse(
            {"success": False, "error": str(e), "points": []}, status=500
        )
