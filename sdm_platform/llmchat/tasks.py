# llmchat/tasks.py
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
    # ... if we're going to get the instructions for a conversation, here's where
    config = RunnableConfig(configurable={"thread_id": thread_name})

    with get_postgres_checkpointer() as checkpointer:
        graph = get_compiled_rag_graph(checkpointer)
        reply = graph.invoke(
            {  # pyright: ignore[reportArgumentType]
                "messages": [
                    HumanMessage(content=user_input, metadata={"username": username}),
                ],
                "turn_citations": [],
                "video_clips": [],
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
            reply["video_clips"],
        )

        if channel_layer := get_channel_layer():
            async_to_sync(channel_layer.group_send)(
                thread_name,
                {
                    "type": "chat.reply",
                    "content": json.dumps(reply_dict),
                },
            )
