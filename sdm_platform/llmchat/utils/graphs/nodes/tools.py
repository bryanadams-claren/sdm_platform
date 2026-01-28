"""Tool execution node - executes tool calls from the LLM."""

import json
import logging
from typing import cast

from langchain_core.messages import AIMessage
from langchain_core.messages import ToolMessage

from sdm_platform.llmchat.utils.graphs.base import SdmState
from sdm_platform.llmchat.utils.tools import show_decision_aid

logger = logging.getLogger(__name__)

# Registry of available tools
TOOLS = {
    "show_decision_aid": show_decision_aid,
}


def create_execute_tools_node():
    """
    Factory function to create execute_tools node.

    Returns:
        Node function that executes tool calls and returns results
    """

    def execute_tools(state: SdmState):
        """
        Execute any tool calls from the last AI message.

        This node runs when the LLM has requested tool calls. It executes each
        tool, collects the results as ToolMessages, and accumulates any
        decision aids to be displayed in the response.
        """
        # Cast to AIMessage since this node only runs when tool_calls exist
        last_message = cast("AIMessage", state["messages"][-1])
        tool_results = []
        decision_aids = list(state.get("turn_decision_aids", []) or [])

        if not last_message.tool_calls:
            logger.warning("execute_tools called but no tool_calls found")
            return {
                "messages": [],
                "next_state": "call_model",
                "turn_decision_aids": decision_aids,
            }

        for tool_call in last_message.tool_calls:
            tool_name = tool_call["name"]
            tool_args = tool_call["args"]
            tool_id = tool_call["id"]

            tool_fn = TOOLS.get(tool_name)
            if tool_fn is None:
                logger.error("Unknown tool requested: %s", tool_name)
                result = {"success": False, "error": f"Unknown tool: {tool_name}"}
            else:
                try:
                    result = tool_fn.invoke(tool_args)
                    logger.info("Tool %s executed successfully", tool_name)
                except Exception:
                    logger.exception("Tool %s failed", tool_name)
                    result = {"success": False, "error": f"Tool {tool_name} failed"}

            # Add tool result message for the LLM
            tool_results.append(
                ToolMessage(
                    content=json.dumps(result),
                    tool_call_id=tool_id,
                )
            )

            # Collect successful decision aids for rendering
            if tool_name == "show_decision_aid" and result.get("success"):
                decision_aids.append(result)

        return {
            "messages": tool_results,
            "next_state": "call_model",
            "user_context": state.get("user_context", ""),
            "system_prompt": state.get("system_prompt", ""),
            "turn_citations": state.get("turn_citations", []) or [],
            "turn_decision_aids": decision_aids,
        }

    return execute_tools
