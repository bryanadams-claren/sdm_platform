"""Utilities for broadcasting AI processing status updates"""

import datetime
import logging
from typing import Any
from zoneinfo import ZoneInfo

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.conf import settings

logger = logging.getLogger(__name__)


def send_status_update(
    thread_name: str,
    event_type: str,
    log_level: int = logging.INFO,
    **data: Any,
) -> None:
    """
    Generic function to broadcast a status update to clients.

    Args:
        thread_name: Thread ID for the conversation
        event_type: Type of status event (e.g., "thinking_start", "extraction_complete")
        log_level: Logging level for this event (default: INFO)
        **data: Additional key-value pairs to include in the status payload
    """
    status_group = f"status_{thread_name}"
    timestamp = datetime.datetime.now(ZoneInfo(settings.TIME_ZONE)).isoformat()

    status_data = {
        "type": event_type,
        "timestamp": timestamp,
        **data,
    }

    if channel_layer := get_channel_layer():
        async_to_sync(channel_layer.group_send)(
            status_group,
            {
                "type": "status.update",
                "data": status_data,
            },
        )
        # Build log message with any extra data
        extra_info = ", ".join(f"{k}={v}" for k, v in data.items()) if data else ""
        log_msg = f"Sent {event_type} status for thread {thread_name}"
        if extra_info:
            log_msg += f" ({extra_info})"
        logger.log(log_level, log_msg)


def send_thinking_start(thread_name: str, trigger: str = "user_message") -> None:
    """
    Notify clients that AI is starting to think/process.

    Args:
        thread_name: Thread ID for the conversation
        trigger: What triggered the AI response
                 Options: "user_message", "conversation_point", "autonomous"
    """
    send_status_update(thread_name, "thinking_start", trigger=trigger)


def send_thinking_end(thread_name: str) -> None:
    """
    Notify clients that AI has finished thinking/processing.

    Args:
        thread_name: Thread ID for the conversation
    """
    send_status_update(thread_name, "thinking_end")


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
    extra: dict[str, Any] = {"stage": stage}
    if message:
        extra["message"] = message
    send_status_update(thread_name, "thinking_progress", logging.DEBUG, **extra)


def send_thinking_stream(thread_name: str, thought: str) -> None:
    """
    Stream a real-time thinking summary (Phase 2+ feature).

    Args:
        thread_name: Thread ID for the conversation
        thought: Summary of what the AI is currently thinking about
    """
    send_status_update(thread_name, "thinking_stream", logging.DEBUG, thought=thought)


def send_extraction_start(thread_name: str) -> None:
    """
    Notify clients that memory extraction is starting.

    Called when the background task begins analyzing conversation points.

    Args:
        thread_name: Thread ID for the conversation
    """
    send_status_update(thread_name, "extraction_start")


def send_extraction_complete(
    thread_name: str, *, summary_triggered: bool = False
) -> None:
    """
    Notify clients that memory extraction has completed.

    Called when the background task finishes analyzing conversation points.

    Args:
        thread_name: Thread ID for the conversation
        summary_triggered: Whether summary generation was triggered (keyword-only)
    """
    send_status_update(
        thread_name, "extraction_complete", summary_triggered=summary_triggered
    )


def send_summary_complete(thread_name: str) -> None:
    """
    Notify clients that summary PDF generation has completed.

    Called when the PDF has been generated and is ready for download.

    Args:
        thread_name: Thread ID for the conversation
    """
    send_status_update(thread_name, "summary_complete")
