"""Background tasks for memory extraction."""

import json
import logging

from celery import shared_task
from langchain.chat_models import init_chat_model
from langchain_core.messages import HumanMessage
from langchain_core.messages import SystemMessage

from sdm_platform.memory.managers import UserProfileManager

logger = logging.getLogger(__name__)

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
