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
from langchain.chat_models import init_chat_model
from langchain_core.messages import AIMessage
from langchain_core.messages import HumanMessage
from langchain_core.messages import SystemMessage
from langchain_core.runnables import RunnableConfig

from sdm_platform.llmchat.utils.format import format_message
from sdm_platform.llmchat.utils.graph import get_compiled_rag_graph
from sdm_platform.llmchat.utils.graph import get_postgres_checkpointer
from sdm_platform.memory.managers import UserProfileManager
from sdm_platform.memory.store import get_memory_store
from sdm_platform.memory.tasks import extract_all_memories
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
    # Get journey slug directly from conversation
    journey_slug = None
    if conversation.journey:
        journey_slug = conversation.journey.slug if conversation.journey else None
        logger.info("Conversation linked to journey: %s", journey_slug)

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

        # Extract all memories (profile + conversation points if journey exists)
        if journey_slug:
            # Extract both profile and conversation point memories
            extract_all_memories.delay(username, journey_slug, recent_messages)  # pyright: ignore[reportCallIssue]
        else:
            # Extract only user profile if no journey
            extract_user_profile_memory.delay(username, recent_messages)  # pyright: ignore[reportCallIssue]


@shared_task()
def send_ai_initiated_message(thread_name: str, username: str, ai_prompt: str):
    """
    Send an AI-initiated message (conversation point prompt).

    Unlike send_llm_reply, this doesn't respond to a user message.
    Instead, the AI proactively starts a conversation about a topic.

    Args:
        thread_name: Thread ID for the conversation
        username: User's email
        ai_prompt: The prompt/question the AI should ask (from conversation point)
    """
    from sdm_platform.llmchat.models import Conversation  # noqa: PLC0415

    logger.info("Sending AI-initiated message for thread %s", thread_name)
    conversation = Conversation.objects.select_related("journey").get(
        thread_id=thread_name
    )

    # Build config with user_id for memory lookup
    config = RunnableConfig(
        configurable={
            "thread_id": thread_name,
            "user_id": username,
        },
    )

    with get_postgres_checkpointer() as checkpointer, get_memory_store() as store:
        # Get the current conversation state to understand context
        graph = get_compiled_rag_graph(checkpointer, store=store)

        # Get the current state to see what's in the conversation
        state = graph.get_state(config)
        existing_messages = state.values.get("messages", []) if state.values else []

        # Load user context for personalization
        profile = UserProfileManager.get_profile(username, store=store)
        user_context = UserProfileManager.format_for_prompt(profile)

        # Build context for the AI's message
        system_context_parts = []
        if conversation.system_prompt:
            system_context_parts.append(conversation.system_prompt)
        if user_context:
            system_context_parts.append(user_context)

        system_context_parts.append(
            "You are proactively starting a new topic in the conversation. "
            f"Ask the user about the following: {ai_prompt}"
        )

        # Call the LLM directly to generate the AI's proactive message
        model = init_chat_model("openai:gpt-4.1")

        # Build messages for the LLM call
        prompt_messages = [SystemMessage(content="\n\n".join(system_context_parts))]

        # Add recent conversation history for context (last 5 messages)
        if existing_messages:
            prompt_messages.extend(existing_messages[-5:])

        # Generate the AI's response
        ai_response = model.invoke(prompt_messages)

        # Create the AI message to add to history
        ai_message = AIMessage(
            content=ai_response.content, metadata={"initiated_conversation_point": True}
        )

        # Update the graph state to include this new AI message
        graph.update_state(
            config,
            {
                "messages": [ai_message],
                "turn_citations": [],
            },
        )

    # Update conversation timestamp
    conversation.updated_at = datetime.datetime.now(ZoneInfo(settings.TIME_ZONE))
    conversation.save()

    # Send the message through WebSocket
    reply_dict = format_message(
        "bot",
        settings.AI_ASSISTANT_NAME,
        ai_response.content,  # pyright: ignore[reportArgumentType]
        datetime.datetime.now(ZoneInfo(settings.TIME_ZONE)),
        [],  # No citations for initiated messages
    )

    if channel_layer := get_channel_layer():
        async_to_sync(channel_layer.group_send)(
            thread_name,
            {
                "type": "chat.reply",
                "content": json.dumps(reply_dict),
            },
        )

    logger.info("AI-initiated message sent successfully for thread %s", thread_name)
