# evidence/services/chroma_health.py
import logging
from typing import Any

import chromadb.errors

from sdm_platform.evidence.utils.chroma import get_chroma_client

logger = logging.getLogger(__name__)


def chroma_health_check() -> dict[str, Any]:
    """
    Try to connect to Chroma (cloud or local) and list collections.
    Returns a dict with status and details.
    """
    try:
        client, client_type = get_chroma_client()  # pyright: ignore[reportGeneralTypeIssues]
    except chromadb.errors.ChromaError as e:
        logger.exception("Failed to initialize chroma client")
        return {"ok": False, "error": f"client_init_failed: {e}"}

    try:
        cols = client.list_collections()
    except chromadb.errors.ChromaError as e:
        logger.exception("Error while listing collections from chroma client")
        return {"ok": False, "error": str(e), "client_type": client_type}

    col_names = [c.name for c in cols]
    # optionally, gather counts for the first few collections (best-effort)
    sample_counts = {}
    for c in cols[:10]:
        try:
            sample_counts[c.name] = c.count()
        except (
            KeyError,
            ValueError,
            TypeError,
            AttributeError,
            IndexError,
            Exception,
        ):
            logger.exception("Failed to get sample count for collection %s", c.name)
            sample_counts[c.name] = None

    return {
        "ok": True,
        "client_type": client_type,
        "collections": col_names,
        "sample_counts": sample_counts,
    }
