"""Service for generating LLM narrative summaries."""

import logging

from django.conf import settings
from langchain.chat_models import init_chat_model
from langchain_core.messages import SystemMessage

from sdm_platform.memory.schemas import ConversationSummaryData

logger = logging.getLogger(__name__)

NARRATIVE_SUMMARY_PROMPT = """You are creating a concise summary document for a patient
to bring to their medical appointment.

Based on the following conversation about {journey_title}, write a brief narrative
summary (400-600 words maximum) that captures the patient's key goals, concerns,
and preferences.

Focus on synthesizing the 3-4 most important themes:
- What matters most to the patient
- Their primary treatment goals
- Key concerns or questions
- Important preferences about treatment approaches

Do NOT enumerate every point discussed. Synthesize and prioritize. Be concise.

IMPORTANT: Some topics may not have been discussed yet. If a topic has no information,
do NOT mention it or say it wasn't discussed - simply focus on the topics that WERE
discussed. Only include information that was actually covered in the conversation.

Write in third person using the patient's first name ("{first_name} mentioned...",
"{his_her} goals include...") to make it appropriate for sharing with healthcare
providers.

Patient Name: {user_name}

Key Conversation Points:
{point_summaries_formatted}

Background:
{onboarding_formatted}

{selected_option_section}

Write a warm, clear summary in 400-600 words (about 1 page) that helps this patient
articulate their values and goals to their healthcare provider. Format it as 3-4
flowing paragraphs. Be specific but concise. If very few topics were discussed,
it's okay to write a shorter summary (200-300 words).
"""


def generate_narrative_summary(summary_data: ConversationSummaryData) -> str:
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

    # Format conversation points (limit to top 3 points and 2 quotes per topic)
    max_points_per_topic = 3
    max_quotes_per_topic = 2

    point_summaries_text = ""
    for i, point in enumerate(summary_data.point_summaries, 1):
        point_summaries_text += f"\n{i}. {point.title}\n"
        if point.extracted_points:
            point_summaries_text += "   Key Points:\n"
            for ep in point.extracted_points[:max_points_per_topic]:
                point_summaries_text += f"   - {ep}\n"
        if point.relevant_quotes:
            point_summaries_text += "   In Their Words:\n"
            for quote in point.relevant_quotes[:max_quotes_per_topic]:
                point_summaries_text += f'   - "{quote}"\n'

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

    # Call LLM with max_tokens to enforce length limit
    model = init_chat_model(settings.LLM_SUMMARY_MODEL, max_tokens=1500)
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
