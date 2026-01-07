# ruff: noqa: ERA001
"""Celery tasks for doing LLM stuff off the hot path"""

import datetime
import json
import logging
from zoneinfo import ZoneInfo

from asgiref.sync import async_to_sync
from celery import shared_task
from channels.layers import get_channel_layer
from django.conf import settings
from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig

from sdm_platform.llmchat.utils.format import format_message
from sdm_platform.llmchat.utils.graph import get_compiled_rag_graph
from sdm_platform.llmchat.utils.graph import get_postgres_checkpointer
from sdm_platform.memory.store import get_memory_store
from sdm_platform.memory.tasks import extract_user_profile_memory

logger = logging.getLogger(__name__)


@shared_task()
def send_llm_reply(thread_name: str, username: str, user_input: str):
    """
    Return an LLM response to user input (via a channel)
    """
    from sdm_platform.llmchat.models import Conversation  # noqa: PLC0415

    # -- get the thread / conversation id elsewhere
    logger.info("Launching LLM reply for thread name %s", thread_name)
    conversation = Conversation.objects.get(thread_id=thread_name)

    # Get journey slug if this conversation is linked to a journey
    # journey_slug = None
    # if hasattr(conversation, "journey_response") and conversation.journey_response:
    #     journey_slug = conversation.journey_response.journey.slug

    # Build config with user_id for memory lookup
    config = RunnableConfig(
        configurable={
            "thread_id": thread_name,
            "user_id": username,  # Used by load_user_context node
            # "journey_slug": journey_slug,  # For future journey memory
        },
    )
    with get_postgres_checkpointer() as checkpointer, get_memory_store() as store:
        graph = get_compiled_rag_graph(checkpointer, store=store)
        reply = graph.invoke(
            {  # pyright: ignore[reportArgumentType]
                "messages": [
                    HumanMessage(content=user_input, metadata={"username": username}),
                ],
                "user_context": "",  # Will be populated by load_user_context node
                "system_prompt": conversation.system_prompt,
                "turn_citations": [],
            },
            config,
        )

    conversation.updated_at = datetime.datetime.now(ZoneInfo(settings.TIME_ZONE))
    conversation.save()

    if reply["messages"][-1].type == "ai":
        # -- only if the LLM replied do we need to
        reply_dict = format_message(
            "bot",
            settings.AI_ASSISTANT_NAME,
            reply["messages"][-1].content,
            datetime.datetime.now(ZoneInfo(settings.TIME_ZONE)),
            reply["turn_citations"],
        )

        if channel_layer := get_channel_layer():
            async_to_sync(channel_layer.group_send)(
                thread_name,
                {
                    "type": "chat.reply",
                    "content": json.dumps(reply_dict),
                },
            )

        recent_messages = [
            {"role": m.type, "content": m.content}
            for m in reply["messages"][-10:]
            if hasattr(m, "type") and hasattr(m, "content")
        ]

        extract_user_profile_memory.delay(username, recent_messages)  # pyright: ignore[reportCallIssue]
