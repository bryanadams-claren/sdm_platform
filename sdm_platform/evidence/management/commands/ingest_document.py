import logging

from django.core.management.base import BaseCommand
from django.core.management.base import CommandError

from sdm_platform.evidence.models import Document
from sdm_platform.evidence.tasks import ingest_document_task

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Enqueue ingestion of a document by ID"

    def add_arguments(self, parser):
        parser.add_argument("document_id", type=str)

    def handle(self, *args, **options):
        doc_id = options["document_id"]
        try:
            doc = Document.objects.get(id=doc_id)
        except Document.DoesNotExist as err:
            msg = f"Document {doc_id} does not exist"
            raise CommandError(msg) from err

        ingest_document_task.delay(str(doc.id))
        logger.info("Enqueued ingestion for %s", doc_id)
