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
to determine if the human (not the AI) has meaningfully discussed a topic.

TOPIC TO ANALYZE:
{topic_title}

DESCRIPTION:
{topic_description}

KEYWORDS TO LOOK FOR:
{keywords}

{previous_assessment}

RECENT CONVERSATION:
{messages}

Your task:
1. Determine if this topic has been meaningfully discussed in the conversation, and
   to what extent the human has participated
2. Extract key points, quotes, and structured information related to the human's
   understanding of the topic
3. Assign a confidence score (0-1) for how thoroughly the topic was addressed

IMPORTANT INSTRUCTIONS:
- If you see a PREVIOUS ASSESSMENT above, consider it carefully
- If the recent messages don't mention this topic, MAINTAIN the previous confidence
- Only INCREASE confidence if you find new relevant information
- Only DECREASE confidence if you find contradictory information that suggests the
  previous assessment was wrong
- If the topic was previously addressed but isn't mentioned in recent messages,
  that's fine - keep the previous status

Return a JSON object with this structure:
{{
    "is_addressed": boolean,
    "confidence_score": float between 0 and 1,
    "extracted_points": [list of key points discussed],
    "relevant_quotes": [list of relevant user quotes from the human],
    "structured_data": {{any structured information you can extract}},
    "reasoning": "Brief explanation of your assessment"
}}

Guidelines:
- is_addressed should be true only if the confidence score is above 0.9
- confidence_score should reflect how thoroughly/clearly the topic was covered and
  must include evidence the human understands and participated in the content
- Only include direct information from the conversation, don't infer
- If the topic wasn't discussed at all, return is_addressed=false and
confidence_score=0.0

Return ONLY valid JSON, no other text."""


@shared_task()
def extract_conversation_point_memories(  # noqa: C901, PLR0912, PLR0915
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
        return None

    try:
        # Get all conversation points for this journey
        points = ConversationPoint.objects.filter(
            journey__slug=journey_slug,
            is_active=True,
        )

        if not points.exists():
            logger.debug("No conversation points found for journey %s", journey_slug)
            return None

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

                if existing_memory:
                    logger.info(
                        "Found existing memory for %s: is_addressed=%s, "
                        "confidence=%.2f",
                        point.slug,
                        existing_memory.is_addressed,
                        existing_memory.confidence_score,
                    )
                else:
                    logger.info("No existing memory found for %s", point.slug)

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

                # Prepare extraction prompt with previous assessment context
                keywords_str = ", ".join(point.semantic_keywords or [])

                # Build previous assessment context if it exists
                previous_assessment = ""
                if existing_memory:
                    max_quotes = 2
                    prev_quotes = (
                        existing_memory.relevant_quotes[:max_quotes]
                        if len(existing_memory.relevant_quotes) > max_quotes
                        else existing_memory.relevant_quotes
                    )
                    previous_assessment = f"""
PREVIOUS ASSESSMENT:
- Status: {"Addressed" if existing_memory.is_addressed else "Not yet addressed"}
- Confidence: {existing_memory.confidence_score:.2f}
- Previously extracted points: {existing_memory.extracted_points}
- Previous quotes: {prev_quotes}
- Last analyzed: {existing_memory.last_analyzed_at}
"""

                extraction_messages = [
                    SystemMessage(
                        content=CONVERSATION_POINT_EXTRACTION_PROMPT.format(
                            topic_title=point.title,
                            topic_description=point.description,
                            keywords=keywords_str,
                            previous_assessment=previous_assessment,
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

                # Smart merge: combine new extraction with existing memory
                new_confidence = float(extracted.get("confidence_score", 0.0))
                new_is_addressed = extracted.get("is_addressed", False)
                new_points = extracted.get("extracted_points", [])
                new_quotes = extracted.get("relevant_quotes", [])
                new_structured = extracted.get("structured_data", {})

                # If we have existing memory, merge intelligently
                if existing_memory:
                    # Never decrease confidence - only increase or maintain
                    merged_confidence = max(
                        existing_memory.confidence_score, new_confidence
                    )

                    logger.info(
                        "Merging %s: existing_conf=%.2f, new_conf=%.2f, "
                        "merged_conf=%.2f",
                        point.slug,
                        existing_memory.confidence_score,
                        new_confidence,
                        merged_confidence,
                    )

                    # If previously addressed, stay addressed (don't regress)
                    merged_is_addressed = (
                        existing_memory.is_addressed or new_is_addressed
                    )

                    # Merge extracted points (combine unique points)
                    existing_points_set = set(existing_memory.extracted_points)
                    new_points_set = set(new_points)
                    merged_points = list(existing_points_set | new_points_set)

                    # Merge quotes (keep unique, limit to 10 most recent)
                    existing_quotes_set = set(existing_memory.relevant_quotes)
                    new_quotes_set = set(new_quotes)
                    merged_quotes = list(existing_quotes_set | new_quotes_set)[-10:]

                    # Merge structured data (new values override old)
                    merged_structured = {
                        **existing_memory.structured_data,
                        **new_structured,
                    }
                else:
                    # No existing memory, use new values
                    merged_confidence = new_confidence
                    merged_is_addressed = new_is_addressed
                    merged_points = new_points
                    merged_quotes = new_quotes
                    merged_structured = new_structured

                # Update semantic memory in LangGraph store (SINGLE SOURCE OF TRUTH)
                updates = {
                    "is_addressed": merged_is_addressed,
                    "confidence_score": merged_confidence,
                    "extracted_points": merged_points,
                    "relevant_quotes": merged_quotes,
                    "structured_data": merged_structured,
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
        return False
    else:
        # Check if all points are addressed and trigger PDF generation if so
        return check_and_trigger_summary_generation(user_id, journey_slug)


@shared_task()
def extract_all_memories(
    user_id: str,
    journey_slug: str,
    messages_json: list[dict],
    thread_id: str | None = None,
):
    """
    Combined task to extract all types of memories.

    This can be called after each conversation turn to extract:
    - User profile information
    - Conversation point semantic memories

    Sends WebSocket events to notify frontend of extraction progress.

    Args:
        user_id: User identifier (email)
        journey_slug: Journey slug (optional, for conversation points)
        messages_json: Recent messages as list of {"role": str, "content": str}
        thread_id: Thread ID for WebSocket status updates (optional)
    """
    # Import here to avoid circular imports
    from sdm_platform.llmchat.utils.status import (  # noqa: PLC0415
        send_extraction_complete,
    )
    from sdm_platform.llmchat.utils.status import send_extraction_start  # noqa: PLC0415

    # Notify frontend that extraction is starting
    if thread_id:
        send_extraction_start(thread_id)

    summary_triggered = False
    try:
        # Extract user profile
        extract_user_profile_memory(user_id, messages_json)

        # Extract conversation point memories (if journey specified)
        if journey_slug:
            summary_triggered = (
                extract_conversation_point_memories(
                    user_id,
                    journey_slug,
                    messages_json,
                )
                or False
            )
    finally:
        # Always notify frontend that extraction is complete
        if thread_id:
            send_extraction_complete(thread_id, summary_triggered=summary_triggered)


@shared_task(bind=True, soft_time_limit=300, time_limit=600, max_retries=2)
def generate_conversation_summary_pdf(self, conversation_id: str) -> str:
    """
    Generate PDF summary for a completed conversation.

    Called automatically when all conversation points are addressed.

    Args:
        conversation_id: Conversation conv_id

    Returns:
        ConversationSummary ID as string
    """
    from django.core.files.base import ContentFile  # noqa: PLC0415

    from sdm_platform.llmchat.models import Conversation  # noqa: PLC0415
    from sdm_platform.memory.models import ConversationSummary  # noqa: PLC0415
    from sdm_platform.memory.services.narrative import (  # noqa: PLC0415
        generate_narrative_summary,
    )
    from sdm_platform.memory.services.pdf_generator import (  # noqa: PLC0415
        ConversationSummaryPDFGenerator,
    )
    from sdm_platform.memory.services.summary import (  # noqa: PLC0415
        ConversationSummaryService,
    )

    try:
        conversation = Conversation.objects.get(conv_id=conversation_id)

        # Check if summary already exists
        if hasattr(conversation, "summary"):
            logger.info(
                "Summary already exists for conversation %s",
                conversation_id,
            )
            return str(conversation.summary.id)

        # Gather data
        service = ConversationSummaryService(conversation)
        summary_data = service.get_summary_data()

        # Generate narrative via LLM
        narrative = generate_narrative_summary(summary_data)
        summary_data.narrative_summary = narrative

        # Generate PDF
        generator = ConversationSummaryPDFGenerator(summary_data)
        pdf_buffer = generator.generate()

        # Save to model
        summary = ConversationSummary(
            conversation=conversation,
            narrative_summary=narrative,
        )
        filename = (
            f"summary_{conversation_id}_{datetime.now(UTC).strftime('%Y%m%d')}.pdf"
        )
        summary.file.save(filename, ContentFile(pdf_buffer.getvalue()))
        summary.save()

        logger.info("Generated summary PDF for conversation %s", conversation_id)

        # Notify frontend that summary is ready
        if conversation.thread_id:
            from sdm_platform.llmchat.utils.status import (  # noqa: PLC0415
                send_summary_complete,
            )

            send_summary_complete(conversation.thread_id)

        return str(summary.id)

    except Exception as exc:
        logger.exception(
            "Error generating PDF for conversation %s",
            conversation_id,
        )
        raise self.retry(exc=exc) from exc


def check_and_trigger_summary_generation(
    user_id: str,
    journey_slug: str,
) -> bool:
    """
    Check if all points are addressed and trigger PDF generation if so.

    Called at the end of extract_conversation_point_memories.

    Args:
        user_id: User identifier (email)
        journey_slug: Journey slug

    Returns:
        True if summary generation was triggered, False otherwise
    """
    from sdm_platform.journeys.models import Journey  # noqa: PLC0415
    from sdm_platform.journeys.models import JourneyResponse  # noqa: PLC0415
    from sdm_platform.memory.services.summary import (  # noqa: PLC0415
        ConversationSummaryService,
    )
    from sdm_platform.users.models import User  # noqa: PLC0415

    try:
        # Find the conversation via JourneyResponse
        user = User.objects.get(email=user_id)
        journey = Journey.objects.get(slug=journey_slug)
        journey_response = JourneyResponse.objects.get(user=user, journey=journey)
        conversation = journey_response.conversation

        if not conversation:
            logger.warning(
                "No conversation found for user %s, journey %s",
                user_id,
                journey_slug,
            )
            return False

        # Skip if summary already exists
        if hasattr(conversation, "summary"):
            return False

        service = ConversationSummaryService(conversation)
        if service.is_complete():
            logger.info(
                "All points addressed for %s, triggering PDF generation",
                conversation.conv_id,
            )
            generate_conversation_summary_pdf.delay(conversation.conv_id)  # pyright: ignore[reportCallIssue]
            return True
        return False  # noqa: TRY300
    except (User.DoesNotExist, Journey.DoesNotExist, JourneyResponse.DoesNotExist):
        logger.warning(
            "Could not find user/journey/response for %s/%s when checking summary",
            user_id,
            journey_slug,
        )
        return False
    except Exception:
        logger.exception(
            "Error checking summary generation for user %s, journey %s",
            user_id,
            journey_slug,
        )
        return False
