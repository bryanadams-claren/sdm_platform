import uuid
from logging import getLogger

import chromadb.errors
from django.conf import settings
from django.db import models

from sdm_platform.evidence.utils.chroma import get_chroma_client

logger = getLogger(__name__)


class Document(models.Model):
    """
    Represents an uploaded document with versioning and lifecycle controls.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    file = models.FileField(upload_to="documents/")
    name = models.CharField(max_length=255)
    content_type = models.CharField(max_length=100, blank=True, default="")

    text_content = models.TextField(blank=True, default="")

    # chunking params
    chunk_size = models.PositiveIntegerField(default=500)
    chunk_overlap = models.PositiveIntegerField(default=50)

    # lifecycle
    version = models.PositiveIntegerField(default=1)
    is_active = models.BooleanField(default=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(blank=True, null=True, default=None)
    is_processed = models.BooleanField(default=False)

    # vector DB integration
    chroma_collection = models.CharField(max_length=255, blank=True, default="")
    vector_count = models.PositiveIntegerField(default=0)

    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )

    def __str__(self):
        return f"{self.name} (v{self.version})"

    def bump_version(self):
        self.version += 1
        self.is_processed = False
        self.processed_at = None
        self.save(update_fields=["version", "is_processed", "processed_at"])

    def delete(self, *args, **kwargs):  # pyright: ignore[reportIncompatibleMethodOverride]
        """Ensure deletion cascades to Chroma."""
        client, _ = get_chroma_client()
        collection_name = self.chroma_collection or f"doc_{self.id}"

        try:
            collection = client.get_collection(collection_name)
            collection.delete(where={"document_id": str(self.id)})
            logger.info("Deleted vectors for Document %s", self.id)
        except chromadb.errors.ChromaError:
            logger.exception("Failed to delete vectors for Document %s", self.id)
        super().delete(*args, **kwargs)


class DocumentChunk(models.Model):
    """
    Stores document chunks tied to a specific version.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    document = models.ForeignKey(
        Document,
        on_delete=models.CASCADE,
        related_name="chunks",
    )
    chunk_index = models.PositiveIntegerField()
    text = models.TextField()
    text_hash = models.CharField(max_length=64, blank=True, default="")
    embedding_cached = models.JSONField(blank=True, default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("document", "chunk_index")

    def __str__(self):
        return (
            f"{self.document.name} v{self.document.version} - chunk {self.chunk_index}"
        )
