"""Routing nodes - mode-specific logic for determining LLM invocation."""

import logging

from sdm_platform.llmchat.utils.graphs.base import SdmState

logger = logging.getLogger(__name__)


def create_assistant_human_turn():
    """
    Assistant mode: Only respond to @llm messages.

    This is the original behavior where the LLM only participates
    when explicitly invoked with the @llm prefix.
    """

    def human_turn(state: SdmState):
        """
        A human is speaking, LLM only responds if invoked with @llm prefix.
        """
        msgs = state["messages"]
        user_context = state.get("user_context", "")
        system_prompt = state.get("system_prompt", "")

        try:
            last_msg_content = str(state.get("messages", [])[-1].content)
        except (IndexError, AttributeError) as e:
            logger.exception("No messages found", exc_info=e)
            return {
                "messages": msgs,
                "next_state": "END",
                "user_context": user_context,
                "system_prompt": system_prompt,
                "turn_citations": [],
            }

        logger.info("assistant_human_turn: %s", last_msg_content[:50])

        # ASSISTANT MODE: Only respond to @llm prefix
        if last_msg_content.strip().startswith("@llm"):
            next_state = "retrieve_and_augment"
        else:
            next_state = "END"

        return {
            "messages": msgs,
            "next_state": next_state,
            "user_context": user_context,
            "system_prompt": system_prompt,
            "turn_citations": [],
        }

    return human_turn


def create_autonomous_human_turn():
    """
    Autonomous mode: Respond to every human message.

    This mode is for 1:1 human-AI conversations where the LLM
    responds to every message without requiring a prefix.
    """

    def human_turn(state: SdmState):
        """
        A human is speaking, LLM always responds to human messages.
        """
        msgs = state["messages"]
        user_context = state.get("user_context", "")
        system_prompt = state.get("system_prompt", "")

        try:
            last_msg = state.get("messages", [])[-1]
            last_msg_type = getattr(last_msg, "type", None)

            # Only respond to human messages
            if last_msg_type != "human":
                logger.debug("autonomous_human_turn: skipping non-human message")
                return {
                    "messages": msgs,
                    "next_state": "END",
                    "user_context": user_context,
                    "system_prompt": system_prompt,
                    "turn_citations": [],
                }

            last_msg_content = str(last_msg.content)
        except (IndexError, AttributeError) as e:
            logger.exception("No messages found", exc_info=e)
            return {
                "messages": msgs,
                "next_state": "END",
                "user_context": user_context,
                "system_prompt": system_prompt,
                "turn_citations": [],
            }

        logger.info("autonomous_human_turn: %s", last_msg_content[:50])

        # AUTONOMOUS MODE: Always respond to human messages
        return {
            "messages": msgs,
            "next_state": "retrieve_and_augment",
            "user_context": user_context,
            "system_prompt": system_prompt,
            "turn_citations": [],
        }

    return human_turn
