# evidence/services/ingest.py
import contextlib
import datetime
import hashlib
import logging
import os
import tempfile
from pathlib import Path
from zoneinfo import ZoneInfo

# these are all for create_batches_local(), b/c the original version just doesn't work
from chromadb.api.types import Documents as chDocuments
from chromadb.api.types import Embeddings as chEmbeddings
from chromadb.api.types import IDs as chIDs
from chromadb.api.types import Metadatas as chMetadatas
from chromadb.errors import ChromaError
from django.conf import settings
from django.urls import reverse
from langchain.embeddings.base import Embeddings
from langchain_community.document_loaders import PyPDFLoader
from langchain_community.document_loaders import TextLoader

# LangChain loaders/splitter/embeddings
from langchain_community.document_loaders import UnstructuredFileLoader
from langchain_community.embeddings import OpenAIEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter

from sdm_platform.evidence.models import Document
from sdm_platform.evidence.models import DocumentChunk
from sdm_platform.evidence.utils.chroma import get_chroma_client

logger = logging.getLogger(__name__)


def create_batches_local(
    ids: chIDs,
    embeddings: chEmbeddings | None = None,
    metadatas: chMetadatas | None = None,
    documents: chDocuments | None = None,
    batch_size=300,
) -> list[tuple[chIDs, chEmbeddings | None, chMetadatas | None, chDocuments | None]]:
    _batches: list[
        tuple[chIDs, chEmbeddings | None, chMetadatas | None, chDocuments | None]
    ] = []
    if len(ids) > batch_size:
        # create split batches
        for i in range(0, len(ids), batch_size):
            _batches.append(  # noqa: PERF401
                (
                    ids[i : i + batch_size],
                    embeddings[i : i + batch_size] if embeddings is not None else None,
                    metadatas[i : i + batch_size] if metadatas else None,
                    documents[i : i + batch_size] if documents else None,
                ),
            )
    else:
        _batches.append((ids, embeddings, metadatas, documents))
    return _batches


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def using_cloud() -> bool:
    if getattr(settings, "CHROMA_USE_CLOUD", None) is not None:
        return bool(settings.CHROMA_USE_CLOUD)
    return bool(os.getenv("CHROMA_API_KEY") or os.getenv("CHROMA_CLOUD_API_KEY"))


class DocumentIngestor:
    """
    Ingest a Document into Chroma with a safe tmp -> perm swap.

    Defaults to OpenAIEmbeddings() when no embedding_model is provided.
    """

    def __init__(self, document: Document, embedding_model: Embeddings | None = None):
        self.document = document
        self.embedding_model = embedding_model or OpenAIEmbeddings()
        self.chroma_client = get_chroma_client()
        logger.info(
            "DocumentIngestor initialized: document=%s use_cloud=%s",
            self.document.id,
            using_cloud(),
        )

    def _load_text(self):
        # Get the file from storage (works with both local and S3)
        with tempfile.NamedTemporaryFile(
            delete=False, suffix=Path(self.document.file.name).suffix
        ) as tmp_file:
            # Read from S3 and write to temp file
            self.document.file.open("rb")
            tmp_file.write(self.document.file.read())
            self.document.file.close()
            file_path = tmp_file.name

        try:
            ext = Path(file_path).suffix.lower()
            if ext == ".pdf":
                loader = PyPDFLoader(file_path)
            elif ext == ".txt":
                loader = TextLoader(file_path, encoding="utf-8")
            else:
                loader = UnstructuredFileLoader(file_path)

            docs = loader.load()
            if not docs:
                errmsg = "No text extracted from file: %s"
                raise RuntimeError(errmsg, file_path)
            return docs
        finally:
            # Clean up the temporary file
            with contextlib.suppress(FileNotFoundError, PermissionError, OSError):
                Path(file_path).unlink()

    def _split(self, docs):
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=self.document.chunk_size,
            chunk_overlap=self.document.chunk_overlap,
        )
        return splitter.split_documents(docs)

    def _compute_embeddings(self, texts: list[str]) -> list[list[float]]:
        if hasattr(self.embedding_model, "embed_documents"):
            return self.embedding_model.embed_documents(texts)
        embeddings = []  # todo: what is the proper declaration here?
        for t in texts:
            if hasattr(self.embedding_model, "embed_query"):
                embeddings.append(self.embedding_model.embed_query(t))
            else:
                errmsg = "Embedding model does not have embed_documents or embed_query"
                raise RuntimeError(errmsg)

        return embeddings

    def ingest(self) -> dict:  # noqa: PLR0912, PLR0915, C901
        logger.info("Starting ingest for document=%s", self.document.id)

        # load & cache full text
        docs = self._load_text()
        full_text = "\n\n".join([d.page_content for d in docs])
        self.document.text_content = full_text
        self.document.save(update_fields=["text_content"])

        # split into chunks
        chunks = self._split(docs)

        # prepare arrays
        texts: chDocuments = []
        metadatas: chMetadatas = []
        ids: chIDs = []

        for i, chunk in enumerate(chunks):
            txt = chunk.page_content
            h = text_hash(txt)
            item_id = f"{self.document.id}_v{self.document.version}_c{i}"
            ids.append(item_id)
            texts.append(txt)
            md = {
                "document_id": str(self.document.id),
                "version": self.document.version,
                "chunk_index": i,
                "text_hash": h,
                "source_url": reverse(
                    "evidence:document_download",
                    args=[self.document.id],
                ),
                "page": chunk.metadata.get("page"),
                "source": getattr(chunk, "metadata", {}).get("source"),
            }
            metadatas.append(md)

            # cache chunk in DB
            DocumentChunk.objects.update_or_create(
                document=self.document,
                chunk_index=i,
                defaults={"text": txt, "text_hash": h},
            )

        # compute embeddings
        embeddings = self._compute_embeddings(texts)

        tmp_col_name = f"doc_{self.document.id}_v{self.document.version}_tmp"
        perm_col_name = f"doc_{self.document.id}_v{self.document.version}"

        # defensive: delete leftover tmp if present
        existing = [c.name for c in self.chroma_client.list_collections()]
        logger.debug("Chroma existing collections (pre-ingest): %s", existing)
        if tmp_col_name in existing:
            try:
                logger.warning("Deleting leftover tmp collection: %s", tmp_col_name)
                self.chroma_client.delete_collection(tmp_col_name)
            except ChromaError:
                logger.exception(
                    "Failed to delete leftover tmp collection: %s",
                    tmp_col_name,
                )

        # create tmp collection and add vectors
        try:
            tmp_col = (
                self.chroma_client.get_or_create_collection(name=tmp_col_name)
                if hasattr(self.chroma_client, "get_or_create_collection")
                else self.chroma_client.create_collection(name=tmp_col_name)
            )
        except ChromaError:
            tmp_col = self.chroma_client.create_collection(name=tmp_col_name)

        # setting the max_api_size doesn't actually work, which is why we have to create
        #  batches manually.  but if they do fix it, you can replace this w/
        #  a statement like self.chroma_client.max_api_size = 300
        batches = create_batches_local(
            ids=ids,
            embeddings=embeddings,
            metadatas=metadatas,
            documents=texts,
        )
        for batch in batches:
            tmp_col.add(*batch)
        logger.info("Added %d vectors to tmp collection %s", len(ids), tmp_col_name)

        # verify tmp count
        count = tmp_col.count()
        if count != len(ids):
            try:
                self.chroma_client.delete_collection(tmp_col_name)
            except ChromaError:
                logger.exception("Error deleting tmp collection after count mismatch.")
            errmsg = f"Chroma wrote {count} vectors but expected {len(ids)}"
            raise RuntimeError(errmsg)

        # create perm collection (delete existing if present)
        existing_after = [c.name for c in self.chroma_client.list_collections()]
        if perm_col_name in existing_after:
            logger.info("Perm collection already exists; deleting: %s", perm_col_name)
            try:
                self.chroma_client.delete_collection(perm_col_name)
            except ChromaError:
                logger.exception(
                    "Failed to delete existing perm collection %s; continuing",
                    perm_col_name,
                )

        if hasattr(self.chroma_client, "get_or_create_collection"):
            perm_col = self.chroma_client.get_or_create_collection(name=perm_col_name)
        else:
            perm_col = self.chroma_client.create_collection(name=perm_col_name)

        batches = create_batches_local(
            ids=ids,
            embeddings=embeddings,
            metadatas=metadatas,
            documents=texts,
        )
        for batch in batches:
            perm_col.add(*batch)
        logger.info(
            "Copied %d vectors into perm collection %s",
            len(ids),
            perm_col_name,
        )

        # delete tmp collection
        try:
            self.chroma_client.delete_collection(tmp_col_name)
            logger.info("Deleted tmp collection %s", tmp_col_name)
        except ChromaError:
            logger.exception(
                "Failed to delete tmp collection %s (non-fatal)",
                tmp_col_name,
            )

        # update document record and clean up the old collection
        old_collection = self.document.chroma_collection
        self.document.chroma_collection = perm_col_name
        self.document.vector_count = count
        self.document.is_processed = True
        self.document.is_active = True
        self.document.processed_at = datetime.datetime.now(ZoneInfo(settings.TIME_ZONE))
        self.document.save(
            update_fields=[
                "chroma_collection",
                "vector_count",
                "is_processed",
                "processed_at",
            ],
        )

        if old_collection and old_collection != perm_col_name:
            try:
                logger.info("Deleting old collection %s", old_collection)
                self.chroma_client.delete_collection(old_collection)
            except ChromaError:
                logger.exception(
                    "Failed to delete old collection %s (non-fatal)",
                    old_collection,
                )

        logger.info(
            "Ingest complete: document=%s -> collection=%s (vectors=%d)",
            self.document.id,
            perm_col_name,
            count,
        )
        return {"collection": perm_col_name, "vector_count": count}
