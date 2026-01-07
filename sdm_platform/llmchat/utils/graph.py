import logging

import environ
from langchain.chat_models import init_chat_model
from langchain_chroma import Chroma
from langchain_core.runnables import RunnableConfig
from langchain_openai import OpenAIEmbeddings
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.graph import END
from langgraph.graph import START
from langgraph.graph import MessagesState
from langgraph.graph import StateGraph
from langgraph.store.base import BaseStore

# helper to get a chroma client (reuse your chroma_health.get_chroma_client if present)
from sdm_platform.evidence.utils.chroma import get_chroma_client
from sdm_platform.memory.managers import UserProfileManager

logger = logging.getLogger(__name__)

CURRENT_MODEL = "openai:gpt-4.1"
## If we ever go back to using Tavily, the block looks like this
# e.g., from langchain_tavily import TavilySearch
# e.g., search_tool = TavilySearch(max_results=2)
# e.g., tools = [search_tool]

# This is the largest "cosine distance" we'll tolerate
# I looked at three whole queries to set this, so who knows if 0.5 is good or not
MAX_DISTANCE_METRIC = 0.5


def get_thing(obj, attr, default=None):
    """Get an attribute from a thing if the thing is a dict or an object."""
    return obj.get(attr) if isinstance(obj, dict) else getattr(obj, attr, default)


def get_postgres_checkpointer():
    env = environ.Env()
    return PostgresSaver.from_conn_string(env.str("DATABASE_URL"))  # pyright: ignore[reportArgumentType]


def _get_collections_to_search(client, limit: int | None = None) -> list[str]:
    """
    Decide which Chroma collections to search.
    By default we search collections that look like doc_<uuid>_v<ver> and optionally a
    global collection.  You may override this logic (e.g., search a single global
    collection for better performance).
    """
    collections = [c.name for c in client.list_collections()]
    # heuristic: prefer collections that start with "doc_" (produced by ingestion)
    doc_cols = [c for c in collections if c.startswith("doc_")]
    cols = doc_cols or collections

    if limit:
        return cols[:limit]
    return cols


def _retrieve_top_k_from_collections(  # noqa: PLR0913
    client,
    query: str,
    embeddings,
    collections: list[str],
    per_collection_k: int = 3,
    max_total_k: int = 5,
) -> list[tuple[object, float, str]]:
    """
    Query each collection for up to per_collection_k results (returns list of tuples
    (document_text, score, metadata) or (Document, score, collection_name)).
    We then merge and return the top max_total_k results across all collections sorted
    by score (descending).
    """
    candidates = []
    for col in collections:
        try:
            vs = Chroma(
                client=client,
                collection_name=col,
                embedding_function=embeddings,
            )
            # similarity_search_with_score usually returns (Document, score) pairs
            docs_and_scores = vs.similarity_search_with_score(query, k=per_collection_k)
            for doc, score in docs_and_scores:
                if score < MAX_DISTANCE_METRIC:
                    candidates.append((doc, float(score), col))
        except Exception:
            logger.exception("Error searching collection %s", col)
            continue

    # "search_with_score" --> lower is better
    # see: https://python.langchain.com/api_reference/community/vectorstores/langchain_community.vectorstores.chroma.Chroma.html
    candidates_sorted = sorted(candidates, key=lambda t: t[1])
    return candidates_sorted[:max_total_k]


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
    system_content_parts = []

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


# --------------------------
# State model
# --------------------------
class SdmState(MessagesState):
    """
    State model used by StateGraph. Persist turn_citations so messages can have links
    to evidence.
    """

    # persisted compact citations for the last assistant reply in this state snapshot
    next_state: str
    # User context loaded from memory (name, preferences, etc.)
    user_context: str
    # System prompt from conversation (journey context, etc.)
    system_prompt: str
    # Citations from the RAG step
    turn_citations: list[dict]


# --------------------------
# Graph builder
# --------------------------
def get_compiled_rag_graph(  # noqa: C901, PLR0915
    checkpointer: PostgresSaver,
    store: BaseStore | None = None,
):
    """
    Build the RAG graph with optional memory support.

    Args:
        checkpointer: PostgresSaver for conversation state
        store: Optional BaseStore (PostgresStore) for long-term memory.
               If provided, user context will be loaded from memory.
    """
    # instantiate model as you did
    model = init_chat_model(CURRENT_MODEL)

    # embedder used for query creation
    embeddings = OpenAIEmbeddings()

    def load_context(state: SdmState, config: RunnableConfig):
        """
        Load all context needed for the conversation:
        - User profile from memory store (name, preferences, etc.)
        - Conversation system prompt (journey responses, etc.)

        This runs at the start of each turn to provide full context.
        """
        user_context = ""
        system_prompt = ""

        # Load user profile from memory store
        if store:
            user_id = config.get("configurable", {}).get("user_id")
            if user_id:
                try:
                    profile = UserProfileManager.get_profile(user_id, store=store)
                    user_context = UserProfileManager.format_for_prompt(profile)
                except Exception:
                    logger.exception("Error loading user context for %s", user_id)

        # Load conversation system prompt (from state if provided)
        # This comes from the initial invoke call in tasks.py
        system_prompt = state.get("system_prompt", "")

        return {
            "user_context": user_context,
            "system_prompt": system_prompt,
        }

    def human_turn(state: SdmState):
        """
        A human is speaking, clankers be quiet until you're called upon
        :param state:
        :return:
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

        logger.info("human_turn: %s", last_msg_content)

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

    def retrieve_and_augment(state: SdmState):
        """
        Retrieve evidence from Chroma and augment messages.
        Context (user_context, system_prompt) should already be loaded.
        """
        msgs = state["messages"]
        user_context = state.get("user_context", "")
        system_prompt = state.get("system_prompt", "")

        # Find last user message
        last_user_text = None
        for m in reversed(msgs):
            role = get_thing(m, "type")
            content = get_thing(m, "content")
            if role == "human" and content:
                last_user_text = content
                break

        if not last_user_text:
            # No user message to process, just add context and continue
            return _build_system_message_and_continue(
                msgs, user_context, system_prompt, []
            )

        # Retrieve evidence from Chroma
        client = get_chroma_client()
        collections = _get_collections_to_search(client, limit=50)
        candidates = _retrieve_top_k_from_collections(
            client=client,
            query=last_user_text,
            embeddings=embeddings,
            collections=collections,
            per_collection_k=2,
            max_total_k=5,
        )

        # Build citations from candidates
        turn_citations = []
        evidence_lines = []
        if candidates:
            for i, (doc_obj, score, col) in enumerate(candidates, start=1):
                md = getattr(doc_obj, "metadata", {}) or {}
                text_excerpt = getattr(doc_obj, "page_content", "") or ""
                doc_id = md.get("document_id") or md.get("source")
                chunk_idx = md.get("chunk_index")

                evidence_lines.append(
                    f"[{i}] (col={col}) doc={doc_id} "
                    f"chunk={chunk_idx} score={score:.4f}\n"
                    f"{text_excerpt}"
                )

                url = md.get("source_url") or md.get("chunk_url")
                if not url and doc_id:
                    url = f"/documents/{doc_id}/download/"

                turn_citations.append(
                    {
                        "index": i,
                        "score": score,
                        "doc_id": doc_id,
                        "collection": col,
                        "chunk_index": chunk_idx,
                        "page": int(md.get("page", 0)),
                        "title": md.get("document_name") or md.get("title") or None,
                        "url": url,
                        "excerpt": text_excerpt,
                    }
                )

        # Build system message with context and evidence
        return _build_system_message_and_continue(
            msgs, user_context, system_prompt, turn_citations, evidence_lines
        )

    # existing call_model node unchanged
    # Node 2: call the model and persist compact turn_citations only
    def call_model(state: SdmState):
        """
        Call the LLM with the augmented messages.
        """
        # call the model - many model wrappers return dict with "messages" key
        model_response = model.invoke(state["messages"])

        # Extract the assistant's final message text from the model response
        # Support multiple shapes: dict {"messages": [...]}, list, or message-like obj
        if isinstance(model_response, dict) and "messages" in model_response:
            response_messages = model_response["messages"]
        elif isinstance(model_response, list):
            response_messages = model_response
        else:  # single message-like object
            response_messages = [model_response]

        # Build final reply dict.
        return {
            "messages": response_messages,
            "next_state": "human_turn",
            "user_context": state.get("user_context", ""),
            "system_prompt": state.get("system_prompt", ""),
            "turn_citations": state.get("turn_citations", []) or [],
        }

    def follow_next_state(state):
        return state["next_state"]

    # Build graph
    builder = StateGraph(SdmState)
    builder.add_node("load_context", load_context)
    builder.add_node("human_turn", human_turn)
    builder.add_node("retrieve_and_augment", retrieve_and_augment)
    builder.add_node("call_model", call_model)

    # Start by loading user context, then proceed to human_turn
    builder.add_edge(START, "load_context")
    builder.add_edge("load_context", "human_turn")
    builder.add_conditional_edges(
        "human_turn",
        follow_next_state,
        {
            "human_turn": "human_turn",
            "retrieve_and_augment": "retrieve_and_augment",
            "call_model": "call_model",
            "END": END,
        },
    )
    builder.add_edge("retrieve_and_augment", "call_model")
    builder.add_edge("call_model", END)

    # Compile and return graph (checkpointer ensures state persistence)
    # Store is passed to nodes via closure
    return builder.compile(checkpointer=checkpointer)
