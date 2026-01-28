"""Assistant mode graph - responds only to @llm messages."""

from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.graph import END
from langgraph.graph import START
from langgraph.graph import StateGraph
from langgraph.store.base import BaseStore

from sdm_platform.llmchat.utils.graphs.base import SdmState
from sdm_platform.llmchat.utils.graphs.nodes import create_assistant_human_turn
from sdm_platform.llmchat.utils.graphs.nodes import create_call_model_node
from sdm_platform.llmchat.utils.graphs.nodes import create_execute_tools_node
from sdm_platform.llmchat.utils.graphs.nodes import create_extract_memories_node
from sdm_platform.llmchat.utils.graphs.nodes import create_load_context_node
from sdm_platform.llmchat.utils.graphs.nodes import create_retrieve_and_augment_node


def build_assistant_graph(
    checkpointer: PostgresSaver,
    store: BaseStore | None = None,
):
    """
    Build the assistant mode graph.

    Behavior: LLM only responds to messages starting with @llm.
    This preserves the original behavior where the LLM acts as an assistant
    in a multi-human conversation, only participating when explicitly invoked.

    Flow:
        START → load_context → human_turn → [routing]
                                              ↓
                              retrieve_and_augment (if @llm)
                                              ↓
                                          call_model ←──┐
                                              ↓         │
                                    [has tool calls?]   │
                                         ↓    ↓         │
                                        no   yes        │
                                         ↓    ↓         │
                               extract_memories  execute_tools
                                         ↓              │
                                        END ────────────┘
    """
    # Create node functions with dependencies injected
    load_context = create_load_context_node(store)
    human_turn = create_assistant_human_turn()
    retrieve_and_augment = create_retrieve_and_augment_node()
    call_model = create_call_model_node()
    execute_tools = create_execute_tools_node()
    extract_memories = create_extract_memories_node()

    def follow_next_state(state):
        return state["next_state"]

    # Build graph
    builder = StateGraph(SdmState)
    builder.add_node("load_context", load_context)
    builder.add_node("human_turn", human_turn)
    builder.add_node("retrieve_and_augment", retrieve_and_augment)
    builder.add_node("call_model", call_model)
    builder.add_node("execute_tools", execute_tools)
    builder.add_node("extract_memories", extract_memories)

    # Define edges
    builder.add_edge(START, "load_context")
    builder.add_edge("load_context", "human_turn")
    builder.add_conditional_edges(
        "human_turn",
        follow_next_state,
        {
            "retrieve_and_augment": "retrieve_and_augment",
            "END": END,
        },
    )
    builder.add_edge("retrieve_and_augment", "call_model")

    # After call_model, route based on whether there are tool calls
    builder.add_conditional_edges(
        "call_model",
        follow_next_state,
        {
            "execute_tools": "execute_tools",
            "extract_memories": "extract_memories",
        },
    )

    # After executing tools, go back to call_model for the LLM to process results
    builder.add_edge("execute_tools", "call_model")

    builder.add_edge("extract_memories", END)

    return builder.compile(checkpointer=checkpointer)
