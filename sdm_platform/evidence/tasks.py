import time

from celery import shared_task
from celery.utils.log import get_task_logger
from django.conf import settings
from langchain.embeddings import init_embeddings

from sdm_platform.evidence.models import Document
from sdm_platform.evidence.services.ingest import DocumentIngestor

logger = get_task_logger(__name__)


@shared_task(
    bind=True,
    soft_time_limit=180,
    time_limit=600,
    max_retries=3,
    default_retry_delay=30,
)
def ingest_document_task(self, document_id):
    """
    Celery task to ingest a Document by id.

    - Uses the configured LLM_EMBEDDING_MODEL from settings.
    - Tracks processing status, duration, and errors.
    - Retries on exception (with exponential backoff configured by Celery defaults).
    """
    try:
        # Load document in a transaction-safe way
        doc = Document.objects.get(id=document_id)
    except Document.DoesNotExist:
        logger.error("Document %s does not exist, cannot ingest", document_id)  # noqa: TRY400
        # No retry if the document record is missing
        raise

    # Mark as processing
    doc.processing_status = Document.ProcessingStatus.PROCESSING
    doc.processing_error = ""
    doc.save(update_fields=["processing_status", "processing_error"])

    start_time = time.time()

    try:
        logger.info(
            "Starting ingestion task for document_id=%s, name=%s",
            document_id,
            doc.name,
        )
        embeddings = init_embeddings(settings.LLM_EMBEDDING_MODEL)
        ingestor = DocumentIngestor(document=doc, embedding_model=embeddings)

        # Run ingest (this does its own DB writes)
        result = ingestor.ingest()

        # Update duration after successful ingestion
        doc.refresh_from_db()
        doc.processing_duration_seconds = time.time() - start_time
        doc.save(update_fields=["processing_duration_seconds"])

        logger.info(
            "Successfully completed ingestion for document_id=%s, result=%s",
            document_id,
            result,
        )
        return result  # noqa: TRY300

    except Exception as exc:
        # Update status to failed with error details
        doc.processing_status = Document.ProcessingStatus.FAILED
        doc.processing_error = str(exc)
        doc.processing_duration_seconds = time.time() - start_time
        doc.save(
            update_fields=[
                "processing_status",
                "processing_error",
                "processing_duration_seconds",
            ]
        )

        logger.exception(
            "Ingestion failed for document_id=%s (retry %s/%s)",
            document_id,
            self.request.retries,
            self.max_retries,
        )
        # Retry with exponential backoff via Celery. Raise self.retry to schedule retry.
        try:
            raise self.retry(exc=exc)  # noqa: TRY301
        except Exception:
            # If retry raises (e.g. MaxRetriesExceededError), reraise original exception
            logger.error(  # noqa: TRY400
                "Max retries exceeded for document_id=%s, giving up",
                document_id,
            )
            raise
