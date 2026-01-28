"""Model calling node - invokes the LLM with augmented messages."""

from sdm_platform.llmchat.utils.graphs.base import SdmState
from sdm_platform.llmchat.utils.graphs.base import get_model
from sdm_platform.llmchat.utils.tools import show_decision_aid

# Tools available to the model
TOOLS = [show_decision_aid]


def create_call_model_node():
    """
    Factory function to create call_model node.

    Returns:
        Node function that calls the LLM with tools bound
    """
    model = get_model()
    model_with_tools = model.bind_tools(TOOLS)

    def call_model(state: SdmState):
        """
        Call the LLM with the augmented messages.

        The model has tools bound (like show_decision_aid) which it may choose
        to call. If it does, the response will contain tool_calls and routing
        will send it to the execute_tools node.
        """
        model_response = model_with_tools.invoke(state["messages"])

        # Extract the assistant's final message text from the model response
        # Support multiple shapes: dict {"messages": [...]}, list, or message-like obj
        if isinstance(model_response, dict) and "messages" in model_response:
            response_messages = model_response["messages"]
        elif isinstance(model_response, list):
            response_messages = model_response
        else:  # single message-like object
            response_messages = [model_response]

        # Determine next state based on whether there are tool calls
        last_message = response_messages[-1] if response_messages else None
        has_tool_calls = bool(getattr(last_message, "tool_calls", None))
        next_state = "execute_tools" if has_tool_calls else "extract_memories"

        return {
            "messages": response_messages,
            "next_state": next_state,
            "user_context": state.get("user_context", ""),
            "system_prompt": state.get("system_prompt", ""),
            "turn_citations": state.get("turn_citations", []) or [],
            "turn_decision_aids": state.get("turn_decision_aids", []) or [],
        }

    return call_model
