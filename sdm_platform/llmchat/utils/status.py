"""Utilities for broadcasting AI processing status updates"""

import datetime
import logging
from zoneinfo import ZoneInfo

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.conf import settings

logger = logging.getLogger(__name__)


def send_thinking_start(thread_name: str, trigger: str = "user_message") -> None:
    """
    Notify clients that AI is starting to think/process.

    Args:
        thread_name: Thread ID for the conversation
        trigger: What triggered the AI response
                 Options: "user_message", "conversation_point", "autonomous"
    """
    status_group = f"status_{thread_name}"
    timestamp = datetime.datetime.now(ZoneInfo(settings.TIME_ZONE)).isoformat()

    status_data = {
        "type": "thinking_start",
        "timestamp": timestamp,
        "trigger": trigger,
    }

    if channel_layer := get_channel_layer():
        async_to_sync(channel_layer.group_send)(
            status_group,
            {
                "type": "status.update",
                "data": status_data,
            },
        )
        logger.info(
            "Sent thinking_start status for thread %s (trigger: %s)",
            thread_name,
            trigger,
        )


def send_thinking_end(thread_name: str) -> None:
    """
    Notify clients that AI has finished thinking/processing.

    Args:
        thread_name: Thread ID for the conversation
    """
    status_group = f"status_{thread_name}"
    timestamp = datetime.datetime.now(ZoneInfo(settings.TIME_ZONE)).isoformat()

    status_data = {
        "type": "thinking_end",
        "timestamp": timestamp,
    }

    if channel_layer := get_channel_layer():
        async_to_sync(channel_layer.group_send)(
            status_group,
            {
                "type": "status.update",
                "data": status_data,
            },
        )
        logger.info("Sent thinking_end status for thread %s", thread_name)


def send_thinking_progress(
    thread_name: str,
    stage: str,
    message: str | None = None,
) -> None:
    """
    Send progress update during AI thinking (Phase 2 feature).

    Args:
        thread_name: Thread ID for the conversation
        stage: Current processing stage
               Options: "loading_context", "generating_response", "extracting_memories"
        message: Optional human-readable message describing current activity
    """
    status_group = f"status_{thread_name}"
    timestamp = datetime.datetime.now(ZoneInfo(settings.TIME_ZONE)).isoformat()

    status_data = {
        "type": "thinking_progress",
        "timestamp": timestamp,
        "stage": stage,
    }

    if message:
        status_data["message"] = message

    if channel_layer := get_channel_layer():
        async_to_sync(channel_layer.group_send)(
            status_group,
            {
                "type": "status.update",
                "data": status_data,
            },
        )
        logger.debug(
            "Sent thinking_progress status for thread %s (stage: %s)",
            thread_name,
            stage,
        )


def send_thinking_stream(thread_name: str, thought: str) -> None:
    """
    Stream a real-time thinking summary (Phase 2+ feature).

    Args:
        thread_name: Thread ID for the conversation
        thought: Summary of what the AI is currently thinking about
    """
    status_group = f"status_{thread_name}"
    timestamp = datetime.datetime.now(ZoneInfo(settings.TIME_ZONE)).isoformat()

    status_data = {
        "type": "thinking_stream",
        "timestamp": timestamp,
        "thought": thought,
    }

    if channel_layer := get_channel_layer():
        async_to_sync(channel_layer.group_send)(
            status_group,
            {
                "type": "status.update",
                "data": status_data,
            },
        )
        logger.debug("Sent thinking_stream status for thread %s", thread_name)
