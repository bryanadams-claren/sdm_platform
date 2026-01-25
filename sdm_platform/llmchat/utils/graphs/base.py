"""Base state schema and shared utilities for all graph modes."""

import logging

import environ
from django.conf import settings
from langchain.chat_models import init_chat_model
from langchain.embeddings import init_embeddings
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.graph import MessagesState

logger = logging.getLogger(__name__)


class SdmState(MessagesState):
    """
    Shared state model used by all graph modes.

    All graphs MUST use this same state schema to ensure:
    - Thread state persists across mode switches
    - Checkpointer compatibility
    - Consistent message handling
    """

    next_state: str
    user_context: str
    system_prompt: str
    turn_citations: list[dict]


def get_model():
    """Get the shared LLM model instance."""
    return init_chat_model(settings.LLM_CHAT_MODEL)


def get_embeddings():
    """Get the shared embeddings instance for RAG."""
    return init_embeddings(settings.LLM_EMBEDDING_MODEL)


def get_thing(obj, attr, default=None):
    """Get an attribute from a thing if the thing is a dict or an object."""
    return obj.get(attr) if isinstance(obj, dict) else getattr(obj, attr, default)


def get_postgres_checkpointer():
    """Get a PostgresSaver checkpointer for graph state persistence."""
    env = environ.Env()
    return PostgresSaver.from_conn_string(env.str("DATABASE_URL"))


GLOBAL_INSTRUCTIONS = (
    "Do not share external video links (e.g., YouTube) as sources may be "
    "unreliable or broken. Focus on text-based explanations and retrieved evidence."
)


def _build_system_message_and_continue(
    msgs: list,
    user_context: str,
    system_prompt: str,
    turn_citations: list,
    evidence_lines: list[str] | None = None,
) -> dict:
    """
    Helper to build system message from context and optional evidence.

    Args:
        msgs: Current message history
        user_context: User profile context (name, etc.)
        system_prompt: Conversation system prompt (journey responses, etc.)
        turn_citations: List of citation dicts
        evidence_lines: Optional list of evidence strings

    Returns:
        State dict with augmented messages
    """
    system_content_parts = [GLOBAL_INSTRUCTIONS]

    # Add conversation context (journey info)
    if system_prompt:
        system_content_parts.append(system_prompt)

    # Add user context (personal info)
    if user_context:
        system_content_parts.append(user_context)

    # Add evidence if available
    if evidence_lines:
        evidence_block = "\n\n".join(evidence_lines)
        system_content_parts.append(
            "RETRIEVED EVIDENCE (for reference when answering). "
            "Each block includes a short excerpt and a citation (e.g., [1], [2])."
            f"\n\n{evidence_block}\n\n"
            "When answering, cite the corresponding evidence blocks"
            " (e.g., [1], [2]) if used."
        )

    # Build and prepend system message if we have any context
    if system_content_parts:
        system_msg = {"role": "system", "content": "\n\n".join(system_content_parts)}
        augmented_messages = [system_msg, *msgs]
    else:
        augmented_messages = msgs

    return {
        "messages": augmented_messages,
        "next_state": "call_model",
        "turn_citations": turn_citations,
        "user_context": user_context,
        "system_prompt": system_prompt,
    }
