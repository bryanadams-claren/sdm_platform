import logging

import chromadb
from django.conf import settings

logger = logging.getLogger(__name__)


def get_chroma_client():
    """
    Return a chromadb client instance (cloud only).
    """
    logger.info("Initializing Chroma Cloud client")
    return chromadb.CloudClient(
        api_key=settings.CHROMA_API_KEY,
        tenant=settings.CHROMA_TENANT,
        database=settings.CHROMA_DATABASE,
    )
