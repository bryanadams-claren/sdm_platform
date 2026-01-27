"""Management command to re-ingest documents to update embeddings or Chroma metadata."""

import logging
import time

from django.conf import settings
from django.core.management.base import BaseCommand
from langchain.embeddings import init_embeddings

from sdm_platform.evidence.models import Document
from sdm_platform.evidence.services.ingest import DocumentIngestor
from sdm_platform.evidence.tasks import ingest_document_task
from sdm_platform.evidence.utils.chroma import get_chroma_client

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Re-ingest documents to update embeddings or Chroma metadata"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be re-ingested without actually doing it",
        )
        parser.add_argument(
            "--cleanup",
            action="store_true",
            help="Delete old Chroma collection after successful re-ingestion",
        )
        parser.add_argument(
            "--document-id",
            type=str,
            help="Re-ingest a specific document by UUID",
        )
        parser.add_argument(
            "--sync",
            action="store_true",
            help="Run synchronously instead of via Celery",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        cleanup = options["cleanup"]
        document_id = options["document_id"]
        sync = options["sync"]

        # Build queryset
        qs = Document.objects.filter(
            processing_status=Document.ProcessingStatus.COMPLETED,
            is_active=True,
        )

        if document_id:
            qs = qs.filter(id=document_id)

        documents = list(qs)
        count = len(documents)

        if count == 0:
            self.stdout.write(self.style.WARNING("No documents found to re-ingest"))
            return

        self.stdout.write(f"Found {count} document(s) to re-ingest")

        if dry_run:
            self._show_dry_run(documents)
            return

        if sync:
            self._run_sync(documents, cleanup)
        else:
            self._run_async(documents, cleanup)

    def _show_dry_run(self, documents):
        """Display what would be re-ingested."""
        for doc in documents:
            journeys = ", ".join(doc.journey_slugs) or "Universal"
            self.stdout.write(
                f"  - {doc.name} (id={doc.id}, journeys: {journeys}, "
                f"collection: {doc.chroma_collection})"
            )

    def _run_async(self, documents, cleanup):
        """Queue documents for re-ingestion via Celery."""
        for doc in documents:
            old_collection = doc.chroma_collection

            # Reset status to queued (version stays the same for metadata-only updates)
            doc.processing_status = Document.ProcessingStatus.QUEUED
            doc.save(update_fields=["processing_status"])

            # Queue the task
            ingest_document_task.delay(str(doc.id))

            self.stdout.write(f"Queued: {doc.name}")

            # Note: cleanup of old collection happens in DocumentIngestor.ingest()
            # when it detects old_collection != new_collection. For same-version
            # re-ingestion, the collection name won't change, so old is overwritten.
            if cleanup and old_collection:
                self.stdout.write(
                    self.style.NOTICE(
                        f"  (old collection {old_collection} will be replaced)"
                    )
                )

        self.stdout.write(
            self.style.SUCCESS(f"Queued {len(documents)} document(s) for re-ingestion")
        )

    def _run_sync(self, documents, cleanup):
        """Run re-ingestion synchronously (useful for debugging)."""
        chroma_client = get_chroma_client()
        embeddings = init_embeddings(settings.LLM_EMBEDDING_MODEL)

        success_count = 0
        fail_count = 0

        for doc in documents:
            old_collection = doc.chroma_collection

            self.stdout.write(f"Processing: {doc.name}...")

            # Mark as processing
            doc.processing_status = Document.ProcessingStatus.PROCESSING
            doc.save(update_fields=["processing_status"])

            start_time = time.time()

            try:
                ingestor = DocumentIngestor(document=doc, embedding_model=embeddings)
                result = ingestor.ingest()

                # Update duration
                doc.refresh_from_db()
                doc.processing_duration_seconds = time.time() - start_time
                doc.save(update_fields=["processing_duration_seconds"])

                self.stdout.write(
                    self.style.SUCCESS(
                        f"  Success: {result['vector_count']} vectors "
                        f"in {doc.processing_duration_seconds:.1f}s"
                    )
                )
                success_count += 1

                # Cleanup old collection if requested and different from new
                if (
                    cleanup
                    and old_collection
                    and old_collection != doc.chroma_collection
                ):
                    try:
                        chroma_client.delete_collection(old_collection)
                        self.stdout.write(f"  Deleted old collection: {old_collection}")
                    except Exception:
                        logger.exception(
                            "Failed to delete old collection %s", old_collection
                        )
                        self.stdout.write(
                            self.style.WARNING(
                                f"  Failed to delete old collection {old_collection}"
                            )
                        )

            except Exception as exc:  # noqa: BLE001
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

                self.stdout.write(self.style.ERROR(f"  Failed: {exc}"))
                fail_count += 1

        self.stdout.write("")
        self.stdout.write(
            self.style.SUCCESS(
                f"Completed: {success_count} success, {fail_count} failed"
            )
        )
