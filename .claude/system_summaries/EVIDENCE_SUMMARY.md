# Evidence System Architecture

This document describes how the evidence/RAG (Retrieval-Augmented Generation) system works in the SDM Platform, enabling the AI to cite medical literature when answering patient questions.

## Overview

The evidence system allows administrators to upload medical documents (PDFs, text files) that are processed, chunked, embedded, and stored in a vector database. When users ask questions during conversations, relevant passages are retrieved and provided to the AI as context, enabling evidence-based responses with citations.

## Key Components

### 1. Document Model

**Model**: `sdm_platform/evidence/models.py` → `Document`

Represents an uploaded document with versioning and processing lifecycle:

```python
class Document(models.Model):
    class ProcessingStatus(models.TextChoices):
        PENDING = "pending"
        QUEUED = "queued"
        PROCESSING = "processing"
        COMPLETED = "completed"
        FAILED = "failed"

    id = UUIDField(primary_key=True)
    file = FileField(upload_to="documents/")
    name = CharField(max_length=255)
    content_type = CharField()
    text_content = TextField()  # Full extracted text

    # Chunking parameters
    chunk_size = PositiveIntegerField(default=500)
    chunk_overlap = PositiveIntegerField(default=50)

    # Lifecycle
    version = PositiveIntegerField(default=1)
    is_active = BooleanField(default=True)
    uploaded_at = DateTimeField(auto_now_add=True)
    processed_at = DateTimeField(null=True)

    # Processing status
    processing_status = CharField(choices=ProcessingStatus.choices, default=PENDING)
    processing_error = TextField(blank=True)  # Error message if failed
    processing_duration_seconds = FloatField(null=True)  # Time to process

    # Vector DB integration
    chroma_collection = CharField()  # Collection name in ChromaDB
    vector_count = PositiveIntegerField(default=0)  # Number of vectors stored
    embedding_model = CharField()  # Model used (e.g., "openai:text-embedding-3-small")

    # Relationships
    uploaded_by = ForeignKey(User, null=True, on_delete=SET_NULL)
    journeys = ManyToManyField(Journey, blank=True)  # Journey scope (empty = universal)

    # Helper properties
    @property
    def journey_slugs(self) -> list[str]:
        """Return list of journey slugs for this document."""
        return list(self.journeys.values_list("slug", flat=True))

    @property
    def is_universal(self) -> bool:
        """Return True if document has no specific journeys (universal)."""
        return not self.journeys.exists()
```

### 2. DocumentChunk Model

**Model**: `sdm_platform/evidence/models.py` → `DocumentChunk`

Stores individual text chunks for reference (the actual embeddings live in ChromaDB):

```python
class DocumentChunk(models.Model):
    id = UUIDField(primary_key=True)
    document = ForeignKey(Document, on_delete=CASCADE, related_name="chunks")
    chunk_index = PositiveIntegerField()
    text = TextField()
    text_hash = CharField(max_length=64)  # SHA-256 for deduplication
    created_at = DateTimeField(auto_now_add=True)
```

### 3. Vector Storage (ChromaDB)

**Client**: `sdm_platform/evidence/utils/chroma.py` → `get_chroma_client()`

The system uses ChromaDB Cloud for vector storage. Configuration:

```python
# Environment variables
CHROMA_API_KEY = "..."  # ChromaDB Cloud API key
CHROMA_TENANT = "..."   # Tenant ID
CHROMA_DATABASE = "..."  # Database name (e.g., "ph-dev")
```

**Collection Naming**: `doc_{document_id}_v{version}`

Each document version gets its own collection, enabling safe atomic updates.

## Configuration (Django Settings)

All LLM and RAG settings are centralized in `config/settings/base.py`:

```python
# Embedding Model
# WARNING: Changing requires re-ingesting ALL documents
LLM_EMBEDDING_MODEL = env("LLM_EMBEDDING_MODEL", default="openai:text-embedding-3-small")

# RAG Retrieval Configuration
# Maximum distance score for results. Lower = better match.
# Range: 0.0 (identical) to 2.0 (opposite) for cosine distance.
RAG_MAX_DISTANCE = env.float("RAG_MAX_DISTANCE", default=1.0)
```

## Document Ingestion Flow

### 1. Upload Document

**Entry Point**: Django Admin or API

**Process**:
1. Document record created with `processing_status=PENDING`
2. File stored in S3 (production) or local filesystem
3. Admin triggers ingestion via action button

### 2. Ingestion Task

**Task**: `sdm_platform/evidence/tasks.py` → `ingest_document_task()`

**Process**:
```
Document uploaded
    ↓
ingest_document_task (Celery)
    ↓
    ├─→ Mark status = PROCESSING
    ├─→ Start timer
    ↓
DocumentIngestor.ingest()
    ↓
    ├─→ Load file (from S3 or local)
    ├─→ Extract text (PyPDF, TextLoader, or UnstructuredFileLoader)
    ├─→ Split into chunks (RecursiveCharacterTextSplitter)
    ├─→ Compute embeddings (init_embeddings from settings)
    ├─→ Create temp collection in ChromaDB
    ├─→ Add vectors to temp collection
    ├─→ Verify vector count
    ├─→ Swap temp → permanent collection (atomic)
    ├─→ Delete old collection if exists
    ↓
Update Document record:
    - processing_status = COMPLETED
    - chroma_collection = collection name
    - vector_count = number of vectors
    - embedding_model = model used
    - processing_duration_seconds = elapsed time
```

**Error Handling**:
- On failure: `processing_status=FAILED`, `processing_error=<message>`
- Task retries up to 3 times with exponential backoff
- Soft time limit: 180s, Hard time limit: 600s

### 3. DocumentIngestor Class

**Class**: `sdm_platform/evidence/services/ingest.py` → `DocumentIngestor`

Key methods:
- `_load_text()` - Extracts text from PDF/TXT/other formats
- `_split(docs)` - Chunks text using LangChain splitter
- `_compute_embeddings(texts)` - Calls embedding model
- `ingest()` - Orchestrates the full pipeline

**Chunking Strategy**:
```python
RecursiveCharacterTextSplitter(
    chunk_size=document.chunk_size,    # Default: 500
    chunk_overlap=document.chunk_overlap  # Default: 50
)
```

**Metadata Stored Per Chunk**:
```python
{
    "document_id": str(document.id),
    "version": document.version,
    "chunk_index": i,
    "text_hash": sha256(text),
    "source_url": "/evidence/documents/{id}/download/",
    "page": page_number,  # If from PDF
    "source": original_filename,
    # Journey filtering metadata
    "is_universal": True/False,  # True if document has no journeys
    "journey_backpain": True,    # Boolean flag per journey (if applicable)
    "journey_kneepain": True,    # etc.
}
```

**Note**: Journey metadata uses boolean flags per journey (e.g., `journey_backpain: True`) because ChromaDB doesn't support `$in` queries on list fields. Documents with no journeys are marked `is_universal: True`.

## RAG Retrieval Flow

### 1. User Sends Message

**Entry Point**: User message in chat

**Graph Node**: `sdm_platform/llmchat/utils/graphs/nodes/retrieval.py` → `retrieve_and_augment`

### 2. Retrieval Process

```
User message received
    ↓
retrieve_and_augment node (receives config with journey_slug)
    ↓
    ├─→ Extract last user message text
    ├─→ Extract journey_slug from config.configurable
    ├─→ Get ChromaDB client
    ├─→ List all collections (doc_* prefix)
    ↓
_build_journey_filter(journey_slug)
    ↓
    Build Chroma $or filter:
    {"$or": [
        {"is_universal": {"$eq": True}},
        {"journey_{slug}": {"$eq": True}}
    ]}
    ↓
_retrieve_top_k_from_collections()
    ↓
    For each collection (up to 50):
        ├─→ Create Chroma vectorstore wrapper
        ├─→ similarity_search_with_score(query, k=2, filter=journey_filter)
        ├─→ Filter results where score < RAG_MAX_DISTANCE
        └─→ Collect candidates
    ↓
Sort all candidates by score (ascending - lower is better)
    ↓
Take top 5 results
    ↓
Build evidence context for system prompt
    ↓
Add citations to turn_citations state
```

### Journey Filtering Logic

| Document State | Chroma Metadata | Returned for "backpain" conversation? |
|---------------|-----------------|--------------------------------------|
| No journeys (universal) | `is_universal: True` | Yes |
| journeys = [backpain] | `journey_backpain: True` | Yes |
| journeys = [kneepain] | `journey_kneepain: True` | No |
| journeys = [backpain, kneepain] | Both flags True | Yes |

### 3. Score Interpretation

The system uses cosine distance (ChromaDB default):

| Score Range | Interpretation |
|-------------|----------------|
| 0.0 - 0.7 | Highly relevant |
| 0.7 - 0.9 | Relevant |
| 0.9 - 1.0 | Somewhat relevant |
| 1.0 - 1.5 | Marginally relevant |
| 1.5 - 2.0 | Irrelevant |

**Threshold**: `RAG_MAX_DISTANCE = 1.0` (configurable)

### 4. Evidence Injection

Retrieved evidence is added to the system prompt:

```
RETRIEVED EVIDENCE (for reference when answering).
Each block includes a short excerpt and a citation (e.g., [1], [2]).

[1] (col=doc_abc123_v1) doc=abc123 chunk=5 score=0.6653
Some patients are more biomedically focused and may question the relevance...

[2] (col=doc_abc123_v1) doc=abc123 chunk=12 score=0.6765
...and providers may be reluctant to change their practice to include...

When answering, cite the corresponding evidence blocks (e.g., [1], [2]) if used.
```

### 5. Citation Tracking

Citations are stored in graph state for potential UI display:

```python
turn_citations = [
    {
        "index": 1,
        "score": 0.6653,
        "doc_id": "abc123",
        "collection": "doc_abc123_v1",
        "chunk_index": 5,
        "page": 12,
        "title": "VA Guidance on LBP",
        "url": "/evidence/documents/abc123/download/",
        "excerpt": "Some patients are more biomedically focused..."
    },
    ...
]
```

## Key Files

### Models
- `sdm_platform/evidence/models.py` - Document, DocumentChunk models

### Ingestion
- `sdm_platform/evidence/tasks.py` - Celery task for async ingestion
- `sdm_platform/evidence/services/ingest.py` - DocumentIngestor class

### Retrieval
- `sdm_platform/llmchat/utils/graphs/nodes/retrieval.py` - RAG retrieval node
- `sdm_platform/llmchat/utils/graphs/base.py` - `get_embeddings()` helper

### ChromaDB
- `sdm_platform/evidence/utils/chroma.py` - Client initialization

### Admin
- `sdm_platform/evidence/admin.py` - Document admin with ingestion actions

### Management Commands
- `sdm_platform/evidence/management/commands/ingest_document.py` - Ingest single document
- `sdm_platform/evidence/management/commands/delete_document_from_chroma.py` - Delete from Chroma
- `sdm_platform/evidence/management/commands/reingest_documents.py` - Bulk re-ingestion

### Configuration
- `config/settings/base.py` - `LLM_EMBEDDING_MODEL`, `RAG_MAX_DISTANCE`

## Admin Interface

**Document Admin** (`/admin/evidence/document/`):

**List Display**:
- Name, Version, Processing Status, Is Active, Vector Count, Journeys (or "Universal"), Uploaded At

**Actions**:
- "Ingest selected documents into Chroma" - Triggers ingestion task
- "Delete selected documents from Chroma" - Removes from both Django and ChromaDB

**Fieldsets**:
- Document Info (name, file, journeys, uploaded_by) - journeys uses `filter_horizontal` for M2M
- Processing (status, error, duration, processed_at)
- Vector Storage (embedding_model, collection, vector_count)
- Chunking Parameters (chunk_size, chunk_overlap)
- Lifecycle (version, is_active, uploaded_at)

## Management Commands

### Ingest Document

```bash
uv run python manage.py ingest_document <document_id>
```

### Delete from Chroma

```bash
uv run python manage.py delete_document_from_chroma <document_id>
```

### Re-ingest Documents

Re-ingest documents to update embeddings or Chroma metadata (e.g., after adding journey associations or changing embedding models):

```bash
# Preview what would be re-ingested
uv run python manage.py reingest_documents --dry-run

# Re-ingest all completed documents (via Celery)
uv run python manage.py reingest_documents

# Re-ingest with old collection cleanup (for embedding model changes)
uv run python manage.py reingest_documents --cleanup

# Re-ingest a specific document synchronously (for debugging)
uv run python manage.py reingest_documents --document-id <uuid> --sync
```

**Options**:
- `--dry-run`: Show what would be re-ingested without doing it
- `--cleanup`: Delete old Chroma collection after successful re-ingestion
- `--document-id <uuid>`: Re-ingest a specific document only
- `--sync`: Run synchronously instead of via Celery (useful for debugging)

## Testing RAG Retrieval

### Manual Test via Django Shell

```python
uv run python manage.py shell -c "
from sdm_platform.evidence.utils.chroma import get_chroma_client
from langchain.embeddings import init_embeddings
from langchain_chroma import Chroma
from django.conf import settings

client = get_chroma_client()
embeddings = init_embeddings(settings.LLM_EMBEDDING_MODEL)

# List collections
collections = [c.name for c in client.list_collections()]
print(f'Collections: {collections}')

# Test query
col_name = collections[0]  # Use first collection
vs = Chroma(client=client, collection_name=col_name, embedding_function=embeddings)
results = vs.similarity_search_with_score('your query here', k=5)

for doc, score in results:
    print(f'Score: {score:.4f}')
    print(f'Content: {doc.page_content[:200]}...')
    print()
"
```

## Embedding Model Considerations

### Changing Embedding Models

**WARNING**: Changing `LLM_EMBEDDING_MODEL` requires re-ingesting ALL documents.

Different embedding models produce incompatible vector spaces. If you change the model:

1. Update `LLM_EMBEDDING_MODEL` in settings
2. Re-ingest all documents via admin
3. Old collections will be replaced with new ones

### Supported Embedding Providers

Via `langchain.embeddings.init_embeddings()`:

- `openai:text-embedding-3-small` (default, 1536 dimensions)
- `openai:text-embedding-3-large` (3072 dimensions)
- `openai:text-embedding-ada-002` (legacy)
- Other providers: Cohere, Google, Bedrock, etc.

### Tracking Embedding Model

Each document stores the embedding model used:

```python
document.embedding_model = "openai:text-embedding-3-small"
```

This enables future migration tools to identify documents needing re-ingestion.

## Journey-Scoped Evidence

Documents can be associated with specific journeys via a ManyToMany relationship:

```python
journeys = ManyToManyField(
    "journeys.Journey",
    blank=True,
    related_name="evidence_documents",
    help_text="Journeys this evidence applies to. Empty = universal."
)
```

**Behavior**:
- **Universal documents** (no journeys): Retrieved for ALL conversations
- **Journey-specific documents**: Only retrieved for conversations in matching journeys
- **Multi-journey documents**: Retrieved for any of the associated journeys

**How it works**:
1. During ingestion, journey metadata is stored as boolean flags in Chroma (e.g., `journey_backpain: True`)
2. During retrieval, `_build_journey_filter()` creates a Chroma `$or` filter
3. Filter matches documents that are either universal OR belong to the current journey

## Performance Considerations

### Collection Search

The system searches up to 50 collections with 2 results each, then takes the top 5 overall. This may need optimization as document count grows.

**Potential Improvements**:
1. Single global collection instead of per-document collections
2. Journey-scoped collections
3. Metadata filtering instead of collection enumeration

### Embedding Calls

Each retrieval makes one embedding API call for the query. Document embeddings are computed once during ingestion.

### ChromaDB Cloud

The system uses ChromaDB Cloud for persistence. Latency depends on network conditions.

## Error Handling

### Ingestion Failures

- Task retries 3 times with 30s delay
- Failed status and error message stored on Document
- Partial collections cleaned up on failure

### Retrieval Failures

- Individual collection errors logged but don't stop search
- Returns empty results if all collections fail
- AI continues without evidence context

## Common Pitfalls

1. **Forgetting to ingest** - Documents must be explicitly ingested after upload

2. **Threshold too strict** - Default was 0.5, now 1.0. Adjust `RAG_MAX_DISTANCE` if needed

3. **Wrong embedding model** - Must match between ingestion and retrieval

4. **ChromaDB credentials** - Ensure `CHROMA_API_KEY`, `CHROMA_TENANT`, `CHROMA_DATABASE` are set

5. **File format issues** - Some PDFs may not extract cleanly; check `text_content` field

6. **Large documents** - Very large documents may hit time limits; consider splitting

## Debugging Tips

### Check Document Status

```python
from sdm_platform.evidence.models import Document

for d in Document.objects.all():
    print(f"{d.name}: {d.processing_status}, vectors={d.vector_count}")
```

### View Chroma Collections

```python
from sdm_platform.evidence.utils.chroma import get_chroma_client

client = get_chroma_client()
for c in client.list_collections():
    print(f"{c.name}: {c.count()} vectors")
```

### Test Specific Query

```python
from django.conf import settings
from langchain.embeddings import init_embeddings
from langchain_chroma import Chroma
from sdm_platform.evidence.utils.chroma import get_chroma_client

client = get_chroma_client()
embeddings = init_embeddings(settings.LLM_EMBEDDING_MODEL)

vs = Chroma(client=client, collection_name="doc_XXX_v1", embedding_function=embeddings)
results = vs.similarity_search_with_score("test query", k=5)

for doc, score in results:
    print(f"Score: {score:.4f} (threshold: {settings.RAG_MAX_DISTANCE})")
    if score < settings.RAG_MAX_DISTANCE:
        print("  ✓ Would be included")
    else:
        print("  ✗ Would be filtered out")
```

## Summary

The evidence system provides:

1. **Document Management** - Upload, version, and track processing status
2. **Text Extraction** - PDF, TXT, and other formats via LangChain loaders
3. **Chunking** - Configurable chunk size/overlap for optimal retrieval
4. **Embedding** - Configurable model via Django settings
5. **Vector Storage** - ChromaDB Cloud with atomic collection updates
6. **RAG Retrieval** - Semantic search with configurable distance threshold
7. **Citation Tracking** - Evidence sources tracked for AI responses

The AI receives relevant evidence as context and is instructed to cite sources, enabling evidence-based responses grounded in uploaded medical literature.
