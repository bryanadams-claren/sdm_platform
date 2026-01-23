"""Views for memory app - conversation points API."""

import logging
from datetime import UTC
from datetime import datetime

from django.contrib.auth.decorators import login_required
from django.http import FileResponse
from django.http import Http404
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.urls import reverse

from sdm_platform.llmchat.models import Conversation
from sdm_platform.llmchat.tasks import send_ai_initiated_message
from sdm_platform.llmchat.utils.format import format_thread_id
from sdm_platform.memory.managers import ConversationPointManager
from sdm_platform.memory.models import ConversationSummary

logger = logging.getLogger(__name__)

_CONVERSATION_NOT_FOUND = "Conversation not found"


def _get_conversation_for_user(user, conv_id, select_related=None):
    """
    Get a conversation, allowing staff to access any conversation.

    Returns the conversation and the actual owner's user object.
    """
    if user.is_staff:
        qs = Conversation.objects.all()
        if select_related:
            qs = qs.select_related(*select_related)
        conv = qs.filter(conv_id=conv_id).first()
        if not conv:
            raise Http404(_CONVERSATION_NOT_FOUND)
        return conv, conv.user

    qs = Conversation.objects.all()
    if select_related:
        qs = qs.select_related(*select_related)
    conv = qs.filter(conv_id=conv_id, user=user).first()
    if not conv:
        raise Http404(_CONVERSATION_NOT_FOUND)
    return conv, user


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
        # Get the conversation (staff can view any conversation)
        conversation, owner = _get_conversation_for_user(request.user, conv_id)

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
        user_id = owner.email

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
                "curiosity_prompt": point.curiosity_prompt,
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


@login_required
def initiate_conversation_point(request, conv_id, point_slug):
    """
    Initiate a conversation point by having the AI proactively ask about it.

    This endpoint is called when a user clicks on a conversation point.
    The AI will use the point's system_message_template to start the conversation.

    Args:
        request: Django request object
        conv_id: Conversation ID
        point_slug: Slug of the conversation point to initiate

    Returns:
        JsonResponse indicating success/failure
    """
    if request.method != "POST":
        return JsonResponse({"success": False, "error": "POST required"}, status=405)

    try:
        # Get the conversation (staff can access any conversation)
        conversation, owner = _get_conversation_for_user(
            request.user, conv_id, select_related=["journey"]
        )

        if not conversation.journey:
            return JsonResponse(
                {
                    "success": False,
                    "error": "No journey associated with this conversation",
                },
                status=400,
            )

        # Get the conversation point
        conversation_point = get_object_or_404(
            conversation.journey.conversation_points,
            slug=point_slug,
            is_active=True,
        )

        # Mark as initiated in memory (optional - for tracking)
        ConversationPointManager.update_point_memory(
            user_id=owner.email,
            journey_slug=conversation.journey.slug,
            point_slug=point_slug,
            updates={
                "manually_initiated": True,
                "initiated_at": datetime.now(UTC).isoformat(),
            },
        )

        # Send AI-initiated message via Celery task
        thread_id = format_thread_id(owner.email, conv_id)
        send_ai_initiated_message.delay(  # pyright: ignore[reportCallIssue]
            thread_id,
            request.user.email,
            conversation_point.slug,
            conversation.journey.slug,
        )

        return JsonResponse(
            {
                "success": True,
                "message": "AI will respond shortly",
                "point_slug": point_slug,
            }
        )

    except Exception as e:
        logger.exception(
            "Error initiating conversation point %s for conv_id=%s", point_slug, conv_id
        )
        return JsonResponse({"success": False, "error": str(e)}, status=500)


@login_required
def conversation_summary_status(request, conv_id):
    """
    Check if conversation summary PDF is ready for download.

    Args:
        request: Django request object
        conv_id: Conversation ID

    Returns:
        JsonResponse with:
        {
            "success": true,
            "ready": true/false,
            "generated_at": "2024-01-15T10:30:00Z",  # if ready
            "download_url": "/memory/conversation/{conv_id}/summary/download/"
            # if ready
        }
    """
    conversation, _owner = _get_conversation_for_user(request.user, conv_id)

    try:
        summary = conversation.summary
        return JsonResponse(
            {
                "success": True,
                "ready": True,
                "generated_at": summary.generated_at.isoformat(),
                "download_url": reverse("memory:download_summary", args=[conv_id]),
            }
        )
    except ConversationSummary.DoesNotExist:
        return JsonResponse(
            {
                "success": True,
                "ready": False,
            }
        )


@login_required
def download_conversation_summary(request, conv_id):
    """
    Download the generated PDF summary.

    Args:
        request: Django request object
        conv_id: Conversation ID

    Returns:
        FileResponse with PDF file
    """
    conversation, _owner = _get_conversation_for_user(request.user, conv_id)

    try:
        summary = conversation.summary
    except ConversationSummary.DoesNotExist:
        return JsonResponse(
            {"success": False, "error": "Summary not yet available"},
            status=404,
        )

    # Return file as download
    response = FileResponse(summary.file, content_type="application/pdf")
    response["Content-Disposition"] = (
        f'attachment; filename="conversation_summary_{conv_id}.pdf"'
    )
    return response
