# evidence/management/commands/delete_document_from_chroma.py
from logging import getLogger

import chromadb.errors
from django.core.management.base import BaseCommand
from django.core.management.base import CommandError

from sdm_platform.evidence.models import Document
from sdm_platform.evidence.utils.chroma import get_chroma_client

logger = getLogger(__name__)


class Command(BaseCommand):
    help = "Delete a document and its embeddings from Chroma."

    def add_arguments(self, parser):
        parser.add_argument(
            "document_id",
            type=str,
            help="UUID of the Document to delete",
        )

    def handle(self, *args, **options):
        doc_id = options["document_id"]

        try:
            document = Document.objects.get(id=doc_id)
        except Document.DoesNotExist as err:
            msg = f"Document {doc_id} does not exist"
            raise CommandError(msg) from err

        client = get_chroma_client()
        collection_name = document.chroma_collection or f"doc_{doc_id}"

        # Delete vectors from Chroma by metadata
        try:
            collection = client.get_collection(collection_name)
            collection.delete(where={"document_id": str(doc_id)})
            client.delete_collection(collection_name)
            logger.info("Deleted vectors for %s from %s", doc_id, collection_name)

        except chromadb.errors.ChromaError:
            logger.exception("ChromaDB error")
            return
        except ConnectionError:
            logger.exception("Failed to connect to ChromaDB")
            return

        # Optionally, delete the document record in Django
        #  ... could run document.delete() here also
        document.processing_status = Document.ProcessingStatus.PENDING
        document.is_active = False
        document.save()

        logger.info("Deleted document record %s from Django and deactivated", doc_id)
