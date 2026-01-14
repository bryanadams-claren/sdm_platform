"""Model calling node - invokes the LLM with augmented messages."""

from sdm_platform.llmchat.utils.graphs.base import SdmState
from sdm_platform.llmchat.utils.graphs.base import get_model


def create_call_model_node():
    """
    Factory function to create call_model node.

    Returns:
        Node function that calls the LLM
    """
    model = get_model()

    def call_model(state: SdmState):
        """
        Call the LLM with the augmented messages.
        """
        model_response = model.invoke(state["messages"])

        # Extract the assistant's final message text from the model response
        # Support multiple shapes: dict {"messages": [...]}, list, or message-like obj
        if isinstance(model_response, dict) and "messages" in model_response:
            response_messages = model_response["messages"]
        elif isinstance(model_response, list):
            response_messages = model_response
        else:  # single message-like object
            response_messages = [model_response]

        return {
            "messages": response_messages,
            "next_state": "extract_memories",
            "user_context": state.get("user_context", ""),
            "system_prompt": state.get("system_prompt", ""),
            "turn_citations": state.get("turn_citations", []) or [],
        }

    return call_model
