# llmchat/tasks.py
import datetime
import json
import logging
import time
from zoneinfo import ZoneInfo

from asgiref.sync import async_to_sync
from celery import shared_task
from channels.layers import get_channel_layer
from django.conf import settings
from django.db import transaction
from langchain_core.messages import AIMessage
from langchain_core.messages import HumanMessage
from langchain_core.messages import SystemMessage
from langchain_core.runnables import RunnableConfig

from sdm_platform.llmchat.utils.chat_history import get_chat_history
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


@shared_task()
def ensure_initial_message_in_langchain(conversation_id) -> bool:
    """
    Idempotently ensure the first assistant message (from the template's
    initial_message)exists in LangChain's chat history for this conversation.

    Returns True if it created the message, False if it was already present or skipped.
    """
    from sdm_platform.llmchat.models import Conversation  # noqa: PLC0415

    logger.info(
        "Kicking off ensure_initial_message_in_langchain for %s",
        conversation_id,
    )
    # Lock the conversation row to avoid duplicate writes under concurrency
    with transaction.atomic():
        tries = 3
        convo = None
        while tries > 0 and not convo:
            try:
                convo = Conversation.objects.select_for_update().get(id=conversation_id)
            except Conversation.DoesNotExist:
                tries = tries - 1
                logger.info(
                    "Conversation %s does not exist yet, %s more tries.",
                    conversation_id,
                    tries,
                )
                time.sleep(1)

        if not convo:
            logger.error("Failed to lock conversation row for initial message sync.")
            return False

        # Only for seed conversations with a template and an initial message
        if (
            not convo.is_seed
            or not convo.template
            or not convo.template.initial_message
        ):
            logger.info(
                "Skipping: convo is not eligible for initial message sync %s / %s / %s",
                convo.is_seed,
                convo.template,
                convo.template.initial_message,
            )
            return False

        thread_id = convo.thread_id
        if not thread_id:
            logger.warning(
                "Conversation %s has no thread_id; cannot sync to LangChain.",
                convo.id,
            )
            return False

        logger.info(
            "Syncing initial AI message for conversation %s (thread_id=%s).",
            convo.id,
            thread_id,
        )
        config = RunnableConfig(configurable={"thread_id": thread_id})
        with get_postgres_checkpointer() as checkpointer:
            graph = get_compiled_rag_graph(checkpointer)
            full_history = list(graph.get_state_history(config=config))
            history = get_chat_history(full_history)

            if history:
                logger.info(
                    "LangChain history already present for thread_id=%s; skipping.",
                    thread_id,
                )
                return False

            logger.info(
                "Syncing init AI message to convo %s with slug %s and thread_id=%s...",
                convo,
                convo.template.slug,
                thread_id,
            )
            initial_messages = []

            # Add system prompt if present
            if convo.system_prompt:
                initial_messages.append(SystemMessage(content=convo.system_prompt))

            # Add initial AI message
            initial_messages.append(AIMessage(content=convo.template.initial_message))

            # ... just a plug to demo a video at this time
            if "treatment-options-videos" in convo.template.slug:
                logger.info(
                    "Adding video clips to treatment-options init conversation!",
                )
                clips = [
                    "/static/videos/lbp_pelvic_tilt.mp4",
                    "/static/videos/lbp_knee_to_chest.mp4",
                    "/static/videos/lbp_trunk_rotations.mp4",
                ]
            else:
                clips = []
            graph.update_state(
                config,
                {
                    "messages": [AIMessage(content=convo.template.initial_message)],
                    "turn_citations": [],
                    "video_clips": clips,
                },
                as_node="call_model",
            )
            logger.info(
                "Created initial AI message for conversation %s (thread_id=%s).",
                convo.id,
                thread_id,
            )
            # -- happy path
            return True
