"""Celery tasks for doing LLM stuff off the hot path"""

import datetime
import json
import logging
from zoneinfo import ZoneInfo

from asgiref.sync import async_to_sync
from celery import shared_task
from channels.layers import get_channel_layer
from django.conf import settings
from django.db.models import F
from django.utils import timezone
from langchain.chat_models import init_chat_model
from langchain_core.messages import AIMessage
from langchain_core.messages import HumanMessage
from langchain_core.messages import SystemMessage
from langchain_core.runnables import RunnableConfig

from sdm_platform.llmchat.utils.format import format_message
from sdm_platform.llmchat.utils.graphs import get_compiled_graph
from sdm_platform.llmchat.utils.graphs import get_postgres_checkpointer
from sdm_platform.llmchat.utils.status import send_thinking_end
from sdm_platform.llmchat.utils.status import send_thinking_start
from sdm_platform.memory.managers import UserProfileManager
from sdm_platform.memory.store import get_memory_store

logger = logging.getLogger(__name__)


def _build_elicitation_context(conversation_point, point_memory) -> list[str]:
    """
    Build system prompt sections for conversation point elicitation.

    Returns a list of prompt sections for elicitation goals, example questions,
    existing memory context, and task instructions.
    """
    sections = []

    # Add conversation point context
    sections.append(
        f"## Conversation Point: {conversation_point.title}\n"
        f"{conversation_point.description}"
    )

    # Add elicitation goals
    if conversation_point.elicitation_goals:
        goals_text = "\n".join(
            f"- {goal}" for goal in conversation_point.elicitation_goals
        )
        sections.append(
            f"## Your Goals for This Discussion\n"
            f"Try to learn the following from the patient:\n{goals_text}"
        )

    # Add example questions as guidance
    if conversation_point.example_questions:
        questions_text = "\n".join(
            f"- {q}" for q in conversation_point.example_questions
        )
        sections.append(f"## Example Questions You Could Adapt\n{questions_text}")

    # Add existing memory context
    has_extracted_points = point_memory and point_memory.extracted_points
    has_relevant_quotes = point_memory and point_memory.relevant_quotes
    if has_extracted_points or has_relevant_quotes:
        memory_parts = ["## What You Already Know About This Topic"]

        if point_memory.extracted_points:
            memory_parts.append("Key points already discussed:")
            memory_parts.extend(f"- {pt}" for pt in point_memory.extracted_points)

        if point_memory.relevant_quotes:
            memory_parts.append("\nRelevant things the patient has said:")
            memory_parts.extend(f'- "{q}"' for q in point_memory.relevant_quotes[:3])

        memory_parts.append(
            "\nBuild on this knowledge. Don't repeat questions about "
            "things you already know. Focus on gaps and deeper exploration."
        )
        sections.append("\n".join(memory_parts))
    else:
        sections.append(
            "## Context\n"
            "This is the first time exploring this topic with the patient. "
            "Start with open-ended questions to understand their situation."
        )

    # Add instruction for the AI
    sections.append(
        "## Your Task\n"
        "The patient has clicked on this conversation topic, indicating "
        "they want to discuss it now. "
        "This is an intentional topic change - the patient is asking "
        "to explore this area.\n\n"
        "Your response should:\n"
        "1. If there was a previous conversation happening, briefly "
        "acknowledge it (1 sentence max) before transitioning to this new topic\n"
        "2. Make it clear you're shifting to discuss what the patient "
        "clicked on\n"
        "3. Ask ONE thoughtful question that helps achieve your "
        "elicitation goals\n\n"
        "Be conversational and empathetic. Don't overwhelm with multiple "
        "questions at once. "
        "Focus entirely on the conversation point goals above."
    )

    return sections


@shared_task()
def send_llm_reply(thread_name: str, username: str, user_input: str):
    """
    Return an LLM response to user input (via a channel)
    """
    from sdm_platform.llmchat.models import Conversation  # noqa: PLC0415

    # Notify clients that AI is starting to think
    # Determine trigger type based on graph mode
    trigger = (
        "autonomous" if settings.LLM_GRAPH_MODE == "autonomous" else "user_message"
    )
    send_thinking_start(thread_name, trigger=trigger)

    try:
        # -- get the thread / conversation id elsewhere
        logger.info("Launching LLM reply for thread name %s", thread_name)
        conversation = Conversation.objects.get(thread_id=thread_name)

        # Get journey slug if this conversation is linked to a journey
        # Get journey slug directly from conversation
        journey_slug = None
        if conversation.journey:
            journey_slug = conversation.journey.slug if conversation.journey else None
            logger.info("Conversation linked to journey: %s", journey_slug)

        # Build config with user_id and journey_slug for memory extraction node
        config = RunnableConfig(
            configurable={
                "thread_id": thread_name,
                "user_id": username,  # Used by load_context and extract_memories nodes
                "journey_slug": journey_slug,  # Used by extract_memories node
            },
        )
        with get_postgres_checkpointer() as checkpointer, get_memory_store() as store:
            graph = get_compiled_graph(checkpointer, store=store)
            reply = graph.invoke(
                {  # pyright: ignore[reportArgumentType]
                    "messages": [
                        HumanMessage(
                            content=user_input, metadata={"username": username}
                        ),
                    ],
                    "user_context": "",  # Will be populated by load_context node
                    "system_prompt": conversation.system_prompt,
                    "turn_citations": [],
                },
                config,
            )

        # Send reply if LLM responded (memory extraction is handled by graph node)
        if reply["messages"][-1].type == "ai":
            # Update conversation analytics (user message + AI response = 2 messages)
            Conversation.objects.filter(thread_id=thread_name).update(
                message_count=F("message_count") + 2,
                last_message_at=timezone.now(),
            )
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
    finally:
        # Always notify that thinking has ended, even if an error occurred
        send_thinking_end(thread_name)


@shared_task()
def send_ai_initiated_message(
    thread_name: str,
    username: str,
    point_slug: str,
    journey_slug: str,
):
    """
    Send an AI-initiated message (conversation point prompt).

    Unlike send_llm_reply, this doesn't respond to a user message.
    Instead, the AI proactively starts a conversation about a topic,
    using existing memory context to ask more targeted questions.

    Args:
        thread_name: Thread ID for the conversation
        username: User's email
        point_slug: Slug of the conversation point to initiate
        journey_slug: Slug of the journey
    """
    from sdm_platform.llmchat.models import Conversation  # noqa: PLC0415
    from sdm_platform.memory.managers import ConversationPointManager  # noqa: PLC0415
    from sdm_platform.memory.models import ConversationPoint  # noqa: PLC0415

    # Notify clients that AI is starting to think (triggered by conversation point)
    send_thinking_start(thread_name, trigger="conversation_point")

    try:
        logger.info("Sending AI-initiated message for thread %s", thread_name)
        conversation = Conversation.objects.select_related("journey").get(
            thread_id=thread_name
        )

        # Get the conversation point with its elicitation guidance
        conversation_point = ConversationPoint.objects.get(
            journey__slug=journey_slug,
            slug=point_slug,
            is_active=True,
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
            graph = get_compiled_graph(checkpointer, store=store)

            # Get the current state to see what's in the conversation
            state = graph.get_state(config)
            existing_messages = state.values.get("messages", []) if state.values else []

            # Load user context for personalization
            profile = UserProfileManager.get_profile(username, store=store)
            user_context = UserProfileManager.format_for_prompt(profile)

            # Load existing memory for this conversation point
            point_memory = ConversationPointManager.get_point_memory(
                user_id=username,
                journey_slug=journey_slug,
                point_slug=point_slug,
                store=store,
            )

            # Build the enhanced system prompt
            system_context_parts = []

            if conversation.system_prompt:
                system_context_parts.append(conversation.system_prompt)

            if user_context:
                system_context_parts.append(user_context)

            # Add elicitation context (goals, examples, memory, instructions)
            system_context_parts.extend(
                _build_elicitation_context(conversation_point, point_memory)
            )

            # Call the LLM directly to generate the AI's proactive message
            model = init_chat_model(settings.LLM_CHAT_MODEL)

            # Build messages for the LLM call
            prompt_messages = [SystemMessage(content="\n\n".join(system_context_parts))]

            # Add recent conversation history for context (last 2-3 messages)
            # Keep this minimal to avoid the AI feeling obligated to
            # continue the previous topic
            if existing_messages:
                prompt_messages.extend(existing_messages[-3:])

            # Add a final emphatic instruction AFTER the conversation history
            # This leverages recency bias to ensure the AI focuses on the
            # conversation point
            goals_text = (
                ", ".join(conversation_point.elicitation_goals[:2])
                if conversation_point.elicitation_goals
                else "this conversation point"
            )
            emphatic_instruction = SystemMessage(
                content=(
                    f"IMPORTANT: The patient has just clicked to discuss "
                    f"'{conversation_point.title}'. "
                    f"Your ONLY task right now is to ask a question about "
                    f"this specific topic. "
                    f"Do NOT continue discussing previous topics unless "
                    f"absolutely necessary for a brief transition. "
                    f"Focus your question on: {goals_text}."
                )
            )
            prompt_messages.append(emphatic_instruction)

            # Generate the AI's response
            ai_response = model.invoke(prompt_messages)

            # Create the AI message to add to history
            ai_message = AIMessage(
                content=ai_response.content,
                metadata={
                    "initiated_conversation_point": True,
                    "conversation_point_slug": point_slug,
                },
            )

            # Update the graph state to include this new AI message
            graph.update_state(
                config,
                {
                    "messages": [ai_message],
                    "turn_citations": [],
                },
            )

        # Update conversation analytics (AI-initiated message = 1 message)
        now = timezone.now()
        Conversation.objects.filter(thread_id=thread_name).update(
            message_count=F("message_count") + 1,
            last_message_at=now,
        )

        # Send the message through WebSocket
        reply_dict = format_message(
            "bot",
            settings.AI_ASSISTANT_NAME,
            ai_response.content,  # pyright: ignore[reportArgumentType]
            now,
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
    finally:
        # Always notify that thinking has ended, even if an error occurred
        send_thinking_end(thread_name)
