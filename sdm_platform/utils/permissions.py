"""
Unified permission utilities for conversation access control.

This module consolidates conversation access checking logic that was previously
duplicated across llmchat/views.py and memory/views.py.
"""

from django.http import Http404

from sdm_platform.llmchat.models import Conversation

_CONVERSATION_NOT_FOUND = "Conversation not found"


def get_conversation_for_user(
    user, conv_id, *, select_related=None, require_owner=False
):
    """
    Get a conversation, with staff access to any conversation.

    Args:
        user: The requesting user
        conv_id: The conversation ID to look up
        select_related: Optional tuple of related fields to prefetch
        require_owner: If True, returns the actual conversation owner
                      (needed for memory lookups where we need the real owner's ID)

    Returns:
        If require_owner=False: Conversation object
        If require_owner=True: (Conversation, owner_user) tuple

    Raises:
        Http404: If conversation not found or user lacks access
    """
    qs = Conversation.objects.all()
    if select_related:
        qs = qs.select_related(*select_related)

    if user.is_staff:
        conv = qs.filter(conv_id=conv_id).first()
        if not conv:
            raise Http404(_CONVERSATION_NOT_FOUND)
        return (conv, conv.user) if require_owner else conv

    conv = qs.filter(conv_id=conv_id, user=user).first()
    if not conv:
        raise Http404(_CONVERSATION_NOT_FOUND)
    return (conv, user) if require_owner else conv


def can_access_conversation(user, conv_id):
    """
    Check if user can access the conversation (owner or staff).

    This is a lightweight check that doesn't fetch the conversation object.
    Use get_conversation_for_user() if you need the actual object.

    Args:
        user: The requesting user
        conv_id: The conversation ID to check

    Returns:
        bool: True if user has access, False otherwise
    """
    if user.is_staff:
        return Conversation.objects.filter(conv_id=conv_id).exists()
    return Conversation.objects.filter(user=user, conv_id=conv_id).exists()
