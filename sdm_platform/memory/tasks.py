"""Background tasks for memory extraction."""

import json
import logging
from datetime import UTC
from datetime import datetime

from celery import shared_task
from langchain.chat_models import init_chat_model
from langchain_core.messages import HumanMessage
from langchain_core.messages import SystemMessage

from sdm_platform.memory.managers import ConversationPointManager
from sdm_platform.memory.managers import UserProfileManager
from sdm_platform.memory.models import ConversationPoint

logger = logging.getLogger(__name__)


HIGH_CONFIDENCE = 0.8

EXTRACTION_MODEL = "openai:gpt-4.1"

EXTRACTION_PROMPT = """Analyze this conversation and extract any new information about
the user.  Only extract information that the user has explicitly stated about
themselves.  Do NOT infer or guess information that wasn't directly stated.

Return a JSON object with any of these fields that you can confidently fill:
- name: User's full name (only if they explicitly stated it)
- preferred_name: How they prefer to be called (only if they explicitly stated it)
- birthday: Their birthday in YYYY-MM-DD format (only if they explicitly stated it)

Only include fields where you have HIGH CONFIDENCE from explicit user statements.
Return an empty object {{}} if no profile information was found.

Conversation:
{messages}

Return ONLY valid JSON, no other text."""


@shared_task()
def extract_user_profile_memory(user_id: str, messages_json: list[dict]):
    """
    Background task to extract profile information from conversation.

    Called after each conversation turn completes. Uses LLM to identify
    any new profile information the user has shared.

    Args:
        user_id: User identifier (email)
        messages_json: Recent messages as list of {"role": str, "content": str}
    """
    if not messages_json:
        return

    model = init_chat_model(EXTRACTION_MODEL)

    # Format messages for extraction
    messages_text = "\n".join(
        [f"{m.get('role', 'unknown')}: {m.get('content', '')}" for m in messages_json],
    )

    extraction_messages = [
        SystemMessage(content=EXTRACTION_PROMPT.format(messages=messages_text)),
        HumanMessage(
            content="Extract user profile information from the conversation above.",
        ),
    ]

    try:
        response = model.invoke(extraction_messages)

        # Parse JSON response
        response_text = str(response.content).strip()

        # Handle potential markdown code blocks
        if response_text.startswith("```"):
            # Remove markdown code block wrapper
            lines = response_text.split("\n")
            response_text = "\n".join(lines[1:-1])

        extracted = json.loads(response_text)

        if extracted and isinstance(extracted, dict):
            # Filter out None values and empty strings
            updates = {k: v for k, v in extracted.items() if v}

            if updates:
                UserProfileManager.update_profile(
                    user_id=user_id,
                    updates=updates,
                    source="llm_extraction",
                )
                logger.info(
                    "Extracted profile data for %s: %s",
                    user_id,
                    list(updates.keys()),
                )
            else:
                logger.debug("No profile data extracted for %s", user_id)

    except json.JSONDecodeError as e:
        logger.warning("Failed to parse extraction response for %s: %s", user_id, e)
    except Exception:
        logger.exception("Failed to extract profile for %s", user_id)


CONVERSATION_POINT_EXTRACTION_PROMPT = """You are analyzing a conversation
to determine if specific topics have been discussed.

TOPIC TO ANALYZE:
{topic_title}

DESCRIPTION:
{topic_description}

KEYWORDS TO LOOK FOR:
{keywords}

RECENT CONVERSATION:
{messages}

Your task:
1. Determine if this topic has been meaningfully discussed in the conversation
2. Extract key points, quotes, and structured information related to this topic
3. Assign a confidence score (0-1) for how thoroughly the topic was addressed

Return a JSON object with this structure:
{{
    "is_addressed": boolean,
    "confidence_score": float between 0 and 1,
    "extracted_points": [list of key points discussed],
    "relevant_quotes": [list of relevant user quotes],
    "structured_data": {{any structured information you can extract}},
    "reasoning": "Brief explanation of your assessment"
}}

Guidelines:
- is_addressed should be true only if the confidence score is above the
  confidence_threshold for that conversation point
- confidence_score should reflect how thoroughly/clearly the topic was covered
  with a bias towards the user displaying understanding
- Only include direct information from the conversation, don't infer
- If the topic wasn't discussed at all, return is_addressed=false and
confidence_score=0.0

Return ONLY valid JSON, no other text."""


@shared_task()
def extract_conversation_point_memories(  # noqa: C901
    user_id: str,
    journey_slug: str,
    messages_json: list[dict],
):
    """
    Background task to extract semantic memories for conversation points.

    Analyzes recent messages to determine if conversation points have been
    addressed and extracts relevant information.

    Stores results ONLY in LangGraph store - no Django model syncing needed.

    Args:
        user_id: User identifier (email)
        journey_slug: Journey slug (e.g., "backpain")
        messages_json: Recent messages as list of {"role": str, "content": str}
    """
    if not messages_json:
        return

    try:
        # Get all conversation points for this journey
        points = ConversationPoint.objects.filter(
            journey__slug=journey_slug,
            is_active=True,
        )

        if not points.exists():
            logger.debug("No conversation points found for journey %s", journey_slug)
            return

        model = init_chat_model(EXTRACTION_MODEL)

        # Format messages for extraction
        messages_text = "\n".join(
            [
                f"{m.get('role', 'unknown')}: {m.get('content', '')}"
                for m in messages_json
            ],
        )

        # Process each conversation point
        for point in points:
            try:
                # Get existing memory to avoid re-analyzing
                existing_memory = ConversationPointManager.get_point_memory(
                    user_id=user_id,
                    journey_slug=journey_slug,
                    point_slug=point.slug,
                )

                # Skip if already addressed with high confidence
                if (
                    existing_memory
                    and existing_memory.is_addressed
                    and existing_memory.confidence_score > HIGH_CONFIDENCE
                ):
                    logger.debug(
                        "Skipping %s - already addressed with high confidence",
                        point.slug,
                    )
                    continue

                # Prepare extraction prompt
                keywords_str = ", ".join(point.semantic_keywords or [])

                extraction_messages = [
                    SystemMessage(
                        content=CONVERSATION_POINT_EXTRACTION_PROMPT.format(
                            topic_title=point.title,
                            topic_description=point.description,
                            keywords=keywords_str,
                            messages=messages_text,
                        )
                    ),
                    HumanMessage(
                        content=(
                            "Analyze the conversation and extract "
                            "information about this topic."
                        )
                    ),
                ]

                # Call LLM for extraction
                response = model.invoke(extraction_messages)
                response_text = str(response.content).strip()

                # Handle markdown code blocks
                if response_text.startswith("```"):
                    lines = response_text.split("\n")
                    response_text = "\n".join(lines[1:-1])

                # Parse JSON response
                extracted = json.loads(response_text)

                if not isinstance(extracted, dict):
                    logger.warning(
                        "Invalid extraction response for %s: not a dict",
                        point.slug,
                    )
                    continue

                # Update semantic memory in LangGraph store (SINGLE SOURCE OF TRUTH)
                updates = {
                    "is_addressed": extracted.get("is_addressed", False),
                    "confidence_score": float(extracted.get("confidence_score", 0.0)),
                    "extracted_points": extracted.get("extracted_points", []),
                    "relevant_quotes": extracted.get("relevant_quotes", []),
                    "structured_data": extracted.get("structured_data", {}),
                    "message_count_analyzed": len(messages_json),
                }

                # Set first_addressed_at if newly addressed
                if updates["is_addressed"] and not (
                    existing_memory and existing_memory.first_addressed_at
                ):
                    updates["first_addressed_at"] = datetime.now(UTC).isoformat()

                # Update memory - this is the ONLY place we store the status
                point_memory = ConversationPointManager.update_point_memory(
                    user_id=user_id,
                    journey_slug=journey_slug,
                    point_slug=point.slug,
                    updates=updates,
                )

                logger.info(
                    (
                        "Extracted conversation point memory for %s/%s:"
                        "is_addressed=%s, confidence=%.2f"
                    ),
                    journey_slug,
                    point.slug,
                    point_memory.is_addressed,
                    point_memory.confidence_score,
                )

            except json.JSONDecodeError as e:
                logger.warning(
                    "Failed to parse extraction response for %s: %s",
                    point.slug,
                    e,
                )
            except Exception:
                logger.exception(
                    "Failed to extract memory for conversation point %s",
                    point.slug,
                )

    except Exception:
        logger.exception(
            "Failed to extract conversation point memories for user %s, journey %s",
            user_id,
            journey_slug,
        )


@shared_task()
def extract_all_memories(
    user_id: str,
    journey_slug: str,
    messages_json: list[dict],
):
    """
    Combined task to extract all types of memories.

    This can be called after each conversation turn to extract:
    - User profile information
    - Conversation point semantic memories

    Args:
        user_id: User identifier (email)
        journey_slug: Journey slug (optional, for conversation points)
        messages_json: Recent messages as list of {"role": str, "content": str}
    """
    # Extract user profile
    extract_user_profile_memory(user_id, messages_json)

    # Extract conversation point memories (if journey specified)
    if journey_slug:
        extract_conversation_point_memories(
            user_id,
            journey_slug,
            messages_json,
        )
