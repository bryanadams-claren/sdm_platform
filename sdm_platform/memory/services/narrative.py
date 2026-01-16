"""Service for generating LLM narrative summaries."""

import json
import logging

from langchain.chat_models import init_chat_model
from langchain_core.messages import SystemMessage

from sdm_platform.memory.schemas import ConversationSummaryData

logger = logging.getLogger(__name__)

NARRATIVE_SUMMARY_PROMPT = """You are creating a summary document for a patient to bring
to their medical appointment.
Based on the following conversation about {journey_title}, write a 1-2 page narrative
summary that captures the patient's key inputs, goals, concerns, and preferences.

Focus on:
- What matters most to the patient
- Their treatment goals and timeline expectations
- Key concerns or questions they have
- Any preferences they expressed about treatment approaches
- Important context from their background

Write in third person using the patient's first name ("{first_name} mentioned...",
"{his_her} goals include...") to make it appropriate for sharing with healthcare
providers.

Patient Name: {user_name}

Conversation Points Discussed:
{point_summaries_formatted}

Onboarding Responses:
{onboarding_formatted}

{selected_option_section}

Write a warm, clear summary (approximately 1-2 pages) that helps this patient
articulate their values and goals to their healthcare provider. Format it as flowing
paragraphs, not bullet points. Make it personal and specific to what this patient
shared.
"""


def generate_narrative_summary(summary_data: ConversationSummaryData) -> str:  # noqa: C901
    """
    Use LLM to generate narrative summary from conversation data.

    Args:
        summary_data: Aggregated conversation summary data

    Returns:
        LLM-generated narrative summary text
    """
    # Determine first name and pronouns
    first_name = summary_data.preferred_name or summary_data.user_name.split()[0]

    # Simple pronoun determination (could be enhanced)
    # For now, use "they/their" as gender-neutral default
    his_her = "their"

    # Format conversation points
    point_summaries_text = ""
    for i, point in enumerate(summary_data.point_summaries, 1):
        point_summaries_text += f"\n{i}. {point.title}\n"
        if point.extracted_points:
            point_summaries_text += "   Key Points:\n"
            for ep in point.extracted_points:
                point_summaries_text += f"   - {ep}\n"
        if point.relevant_quotes:
            point_summaries_text += "   In Their Words:\n"
            for quote in point.relevant_quotes:
                point_summaries_text += f'   - "{quote}"\n'
        if point.structured_data:
            point_summaries_text += (
                f"   Structured Data: {json.dumps(point.structured_data, indent=2)}\n"
            )

    # Format onboarding responses
    onboarding_text = ""
    if summary_data.onboarding_responses:
        onboarding_text = "Background Information:\n"
        for key, value in summary_data.onboarding_responses.items():
            onboarding_text += f"- {key}: {value}\n"

    # Format selected option
    selected_option_text = ""
    if summary_data.selected_option:
        opt = summary_data.selected_option
        selected_option_text = f"""
Preferred Treatment Approach:
{first_name} has expressed interest in: {opt.title}
{opt.description}
Expected timeline: {opt.typical_timeline or "Not specified"}
"""

    # Build the prompt
    prompt_text = NARRATIVE_SUMMARY_PROMPT.format(
        journey_title=summary_data.journey_title,
        first_name=first_name,
        his_her=his_her,
        user_name=summary_data.user_name,
        point_summaries_formatted=point_summaries_text,
        onboarding_formatted=onboarding_text,
        selected_option_section=selected_option_text,
    )

    # Call LLM
    model = init_chat_model("openai:gpt-4.1")
    messages = [SystemMessage(content=prompt_text)]

    logger.info(
        "Generating narrative summary for conversation %s",
        summary_data.conversation_id,
    )

    try:
        response = model.invoke(messages)
        narrative = str(response.content).strip()

        logger.info(
            "Generated narrative summary (%d chars) for conversation %s",
            len(narrative),
            summary_data.conversation_id,
        )
    except Exception:
        logger.exception(
            "Failed to generate narrative summary for conversation %s",
            summary_data.conversation_id,
        )
        # Return a fallback summary
        narrative = f"""Summary for {first_name}

This is a summary of the conversation about {summary_data.journey_title}.

{point_summaries_text}

{onboarding_text}

{selected_option_text}
"""

    return narrative
