"""Autonomous mode graph - responds to every human message."""

from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.graph import END
from langgraph.graph import START
from langgraph.graph import StateGraph
from langgraph.store.base import BaseStore

from sdm_platform.llmchat.utils.graphs.base import SdmState
from sdm_platform.llmchat.utils.graphs.nodes import create_autonomous_human_turn
from sdm_platform.llmchat.utils.graphs.nodes import create_call_model_node
from sdm_platform.llmchat.utils.graphs.nodes import create_extract_memories_node
from sdm_platform.llmchat.utils.graphs.nodes import create_load_context_node
from sdm_platform.llmchat.utils.graphs.nodes import create_retrieve_and_augment_node


def build_autonomous_graph(
    checkpointer: PostgresSaver,
    store: BaseStore | None = None,
):
    """
    Build the autonomous mode graph.

    Behavior: LLM responds to every human message (1:1 chat experience).
    This mode is for direct human-AI conversations without requiring
    any prefix or invocation trigger.

    Flow:
        START → load_context → human_turn → retrieve_and_augment
                                              ↓
                                          call_model
                                              ↓
                                       extract_memories
                                              ↓
                                             END
    """
    # Create node functions with dependencies injected
    load_context = create_load_context_node(store)
    human_turn = create_autonomous_human_turn()  # Different routing!
    retrieve_and_augment = create_retrieve_and_augment_node()
    call_model = create_call_model_node()
    extract_memories = create_extract_memories_node()

    def follow_next_state(state):
        return state["next_state"]

    # Build graph
    builder = StateGraph(SdmState)
    builder.add_node("load_context", load_context)
    builder.add_node("human_turn", human_turn)
    builder.add_node("retrieve_and_augment", retrieve_and_augment)
    builder.add_node("call_model", call_model)
    builder.add_node("extract_memories", extract_memories)

    # Define edges - same structure, but human_turn routes differently
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
    builder.add_edge("call_model", "extract_memories")
    builder.add_edge("extract_memories", END)

    return builder.compile(checkpointer=checkpointer)
