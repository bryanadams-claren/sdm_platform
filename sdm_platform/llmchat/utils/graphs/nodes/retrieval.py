"""RAG retrieval node - retrieves evidence from Chroma and augments messages."""

import logging

from django.conf import settings
from langchain_chroma import Chroma
from langchain_core.runnables import RunnableConfig

from sdm_platform.evidence.utils.chroma import get_chroma_client
from sdm_platform.llmchat.utils.graphs.base import SdmState
from sdm_platform.llmchat.utils.graphs.base import _build_system_message_and_continue
from sdm_platform.llmchat.utils.graphs.base import get_embeddings
from sdm_platform.llmchat.utils.graphs.base import get_thing

logger = logging.getLogger(__name__)


def _get_collections_to_search(client, limit: int | None = None) -> list[str]:
    """
    Decide which Chroma collections to search.

    By default we search collections that look like doc_<uuid>_v<ver> and optionally a
    global collection. You may override this logic (e.g., search a single global
    collection for better performance).
    """
    collections = [c.name for c in client.list_collections()]
    # heuristic: prefer collections that start with "doc_" (produced by ingestion)
    doc_cols = [c for c in collections if c.startswith("doc_")]
    cols = doc_cols or collections

    if limit:
        return cols[:limit]
    return cols


def _build_journey_filter(journey_slug: str | None) -> dict | None:
    """
    Build Chroma where filter for journey-aware retrieval.

    Returns documents that are either:
    1. Universal (is_universal=True), OR
    2. Belong to the specified journey (journey_{slug}=True)

    If journey_slug is None, returns None (no filter - all documents).
    """
    if not journey_slug:
        return None

    return {
        "$or": [
            {"is_universal": {"$eq": True}},
            {f"journey_{journey_slug}": {"$eq": True}},
        ]
    }


def _retrieve_top_k_from_collections(  # noqa: PLR0913
    client,
    query: str,
    embeddings,
    collections: list[str],
    journey_slug: str | None = None,
    per_collection_k: int = 3,
    max_total_k: int = 5,
) -> list[tuple[object, float, str]]:
    """
    Query each collection for up to per_collection_k results.

    Returns list of tuples (Document, score, collection_name).
    We then merge and return the top max_total_k results across all collections
    sorted by score (ascending - lower is better for cosine distance).

    If journey_slug is provided, filters to only return documents that are
    either universal or belong to the specified journey.
    """
    candidates = []
    where_filter = _build_journey_filter(journey_slug)

    for col in collections:
        try:
            vs = Chroma(
                client=client,
                collection_name=col,
                embedding_function=embeddings,
            )
            # similarity_search_with_score returns (Document, score) pairs
            # Lower scores = better matches (cosine distance range: 0.0-2.0)
            search_kwargs = {"k": per_collection_k}
            if where_filter:
                search_kwargs["filter"] = where_filter

            docs_and_scores = vs.similarity_search_with_score(query, **search_kwargs)
            for doc, score in docs_and_scores:
                if score < settings.RAG_MAX_DISTANCE:
                    candidates.append((doc, float(score), col))
        except Exception:
            logger.exception("Error searching collection %s", col)
            continue

    # "search_with_score" --> lower is better (cosine distance)
    candidates_sorted = sorted(candidates, key=lambda t: t[1])
    return candidates_sorted[:max_total_k]


def create_retrieve_and_augment_node():
    """
    Factory function to create retrieve_and_augment node.

    Returns:
        Node function that retrieves evidence and augments messages
    """
    embeddings = get_embeddings()

    def retrieve_and_augment(state: SdmState, config: RunnableConfig):
        """
        Retrieve evidence from Chroma and augment messages.
        Context (user_context, system_prompt) should already be loaded.

        Filters evidence by journey if journey_slug is provided in config.
        """
        msgs = state["messages"]
        user_context = state.get("user_context", "")
        system_prompt = state.get("system_prompt", "")

        # Get journey_slug from config for filtering
        configurable = config.get("configurable", {})
        journey_slug = configurable.get("journey_slug")

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
            journey_slug=journey_slug,
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

    return retrieve_and_augment
