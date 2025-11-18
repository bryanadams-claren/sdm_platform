import logging

import environ
from langchain.chat_models import init_chat_model
from langchain_chroma import Chroma
from langchain_openai import OpenAIEmbeddings
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.graph import END
from langgraph.graph import START
from langgraph.graph import MessagesState
from langgraph.graph import StateGraph

# helper to get a chroma client (reuse your chroma_health.get_chroma_client if present)
from sdm_platform.evidence.utils.chroma import get_chroma_client

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


# --------------------------
# State model
# --------------------------
class RagState(MessagesState):
    """
    State model used by StateGraph. Persist turn_citations so messages can have links
    to evidence, and persist video_clips so messages can have links to videos (not yet
    implemented here).
    """

    # persisted compact citations for the last assistant reply in this state snapshot
    next_state: str
    turn_citations: list[dict]
    video_clips: list[dict]


# --------------------------
# Graph builder
# --------------------------
def get_compiled_rag_graph(checkpointer: PostgresSaver):  # noqa: C901, PLR0915
    # instantiate model as you did
    model = init_chat_model(CURRENT_MODEL)

    # embedder used for query creation
    embeddings = OpenAIEmbeddings()

    def human_turn(state: RagState):
        """
        A human is speaking, clankers be quiet until you're called upon
        :param state:
        :return:
        """
        msgs = state["messages"]
        try:
            last_msg_content = str(state.get("messages", [])[-1].content)
        except (IndexError, AttributeError) as e:
            logger.exception("No messages found", exc_info=e)
            return {
                "messages": msgs,
                "next_state": "END",
                "turn_citations": [],
                "video_clips": [],
            }

        logger.info("human_turn: %s", last_msg_content)

        if last_msg_content.strip().startswith("@llm"):
            next_state = "retrieve_and_augment"
        else:
            next_state = "END"

        return {
            "messages": msgs,
            "next_state": next_state,
            "turn_citations": [],
            "video_clips": [],
        }

    # helper node: retrieve and augment messages with top-K evidence
    def retrieve_and_augment(state: RagState):
        """
        Look at state["messages"], find last user message, retrieve top-k
        evidence from Chroma, and return {'messages': augmented_messages}.
        """
        # find last user message content
        msgs = state["messages"]
        if not msgs:
            return {
                "messages": msgs,
                "next_state": "END",
                "turn_citations": [],
                "video_clips": [],
            }

        # messages are a list of dicts like {"role": "user", "content": "..."}
        last_user_text = None
        # iterate from end to find most recent user message
        for m in reversed(msgs):
            role = get_thing(m, "type")
            content = get_thing(m, "content")
            if role == "human" and content:
                last_user_text = content
                break

        if not last_user_text:
            # nothing to retrieve for
            return {
                "messages": msgs,
                "next_state": "END",
                "turn_citations": [],
                "video_clips": [],
            }

        # create chroma client (cloud or local) using your helper
        client = get_chroma_client()
        # pick collections to search (limit to avoid huge fan-out)
        collections = _get_collections_to_search(client, limit=50)

        # retrieve top candidates across collections (configurable)
        candidates = _retrieve_top_k_from_collections(
            client=client,
            query=last_user_text,
            embeddings=embeddings,
            collections=collections,
            per_collection_k=2,
            max_total_k=5,
        )

        if not candidates:
            # nothing found; simply return original messages
            return {
                "messages": msgs,
                "next_state": "END",
                "turn_citations": [],
                "video_clips": [],
            }

        ## For reviewing the relevance scores, uncomment the following:
        ## e.g., relevance_score = sum([sc if sc else 0. for _, sc, _ in candidates])
        ## consider: f"Total score is {relevance_score}; retrieved {len(candidates)}
        #              candidates from {len(collections)} collections.")

        # Build an evidence block summarizing top results (short excerpts + metadata)
        evidence_lines = []
        turn_citations = []
        for i, (doc_obj, score, col) in enumerate(candidates, start=1):
            # doc is a langchain Document object; prefer page_content and metadata
            md = getattr(doc_obj, "metadata", {}) or {}
            ## Take a closer look at the evidence by printing it out
            # e.g., print(f"EVALUATING EVIDENCE w/ score {score}, total length
            #              {len(doc_obj.page_content)}")
            # e.g., pprint(md)
            text_excerpt = getattr(doc_obj, "page_content", "") or ""
            doc_id = md.get("document_id") or md.get("source")
            chunk_idx = md.get("chunk_index")

            evidence_lines.append(
                f"[{i}] (col={col}) doc={doc_id} chunk={chunk_idx} score={score:.4f}\n"
                "{text_excerpt}",
            )

            # -- just finish up the turn citations here
            url = (
                md.get("source_url") or md.get("chunk_url") or None
            )  # chunk URL for the future
            if not url and doc_id:
                # fallback url pattern; adjust to your app's route
                url = f"/documents/{doc_id}/download/"
                ## In the future, if the page is available, we can add it to the URL:
                # with if page: url = f"{url}?page={page}"

            # keep the langchain Document object for runtime use (post-processing) only
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
                    "excerpt": text_excerpt,  # shows during mouseover on the link
                },
            )

        evidence_block = "\n\n".join(evidence_lines)
        # Create a system message that provides the retrieved evidence to the LLM as
        # context.  You can tweak wording to instruct the model how to use evidence
        # (e.g., "Only cite when necessary").
        system_msg = {
            "role": "system",
            "content": (
                "RETRIEVED EVIDENCE (for reference when answering). "
                "Each block includes a short excerpt and a citation (e.g., [1], [2])."
                f"\n\n{evidence_block}\n\n"
                "When answering, cite the corresponding evidence blocks"
                " (e.g., [1], [2]) if used."
            ),
        }

        # Prepend the system message so the model sees evidence before other messages.
        augmented_messages = [system_msg, *msgs]

        return {
            "messages": augmented_messages,
            "next_state": "call_model",
            "turn_citations": turn_citations,
            "video_clips": [],
        }

    # existing call_model node unchanged
    # Node 2: call the model and persist compact turn_citations only
    def call_model(state: RagState):
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
        # - 'messages' will be saved in the state (MessagesState part).
        # - 'turn_citations' WILL be saved because it's part of RagState.

        return {
            "messages": response_messages,
            "next_state": "human_turn",
            "turn_citations": state.get("turn_citations", []) or [],
            "video_clips": [],  # will need to build these somewhere
        }

    def follow_next_state(state):
        return state["next_state"]

    # Build graph
    builder = StateGraph(RagState)
    builder.add_node(human_turn)
    builder.add_node(retrieve_and_augment)
    builder.add_node(call_model)

    builder.add_edge(START, "human_turn")
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
    return builder.compile(checkpointer=checkpointer)
