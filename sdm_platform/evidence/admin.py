from django.contrib import admin
from django.contrib import messages
from django.core.management import CommandError
from django.core.management import call_command

from sdm_platform.evidence.models import Document
from sdm_platform.evidence.models import DocumentChunk


@admin.register(Document)
class DocumentAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "version",
        "processing_status",
        "is_active",
        "vector_count",
        "get_journeys_display",
        "uploaded_at",
    )
    list_filter = ("processing_status", "is_active", "journeys")
    search_fields = ("name",)
    readonly_fields = (
        "processing_error",
        "processing_duration_seconds",
        "embedding_model",
        "vector_count",
        "chroma_collection",
        "processed_at",
        "uploaded_at",
    )
    filter_horizontal = ("journeys",)
    fieldsets = (
        (
            "Document Info",
            {"fields": ("name", "file", "content_type", "journeys", "uploaded_by")},
        ),
        (
            "Processing",
            {
                "fields": (
                    "processing_status",
                    "processing_error",
                    "processing_duration_seconds",
                    "processed_at",
                )
            },
        ),
        (
            "Vector Storage",
            {"fields": ("embedding_model", "chroma_collection", "vector_count")},
        ),
        (
            "Chunking Parameters",
            {"fields": ("chunk_size", "chunk_overlap")},
        ),
        (
            "Lifecycle",
            {"fields": ("version", "is_active", "uploaded_at")},
        ),
    )
    actions = ["ingest_selected", "delete_from_chroma"]

    @admin.display(description="Journeys")
    def get_journeys_display(self, obj):
        """Display journeys or 'Universal' if none."""
        journeys = obj.journeys.all()
        if not journeys:
            return "Universal (all)"
        return ", ".join(j.slug for j in journeys)

    @admin.action(
        description="Ingest selected documents into Chroma",
    )
    def ingest_selected(self, request, queryset):
        for doc in queryset:
            # Mark as queued before starting ingestion
            doc.processing_status = Document.ProcessingStatus.QUEUED
            doc.save(update_fields=["processing_status"])
            call_command("ingest_document", str(doc.id))
        self.message_user(
            request,
            f"Ingestion enqueued for {queryset.count()} document(s).",
        )

    @admin.action(
        description="Delete selected documents from Chroma",
    )
    def delete_from_chroma(self, request, queryset):
        for doc in queryset:
            try:
                call_command("delete_document_from_chroma", str(doc.id))
            except CommandError as e:
                self.message_user(
                    request,
                    f"Error deleting {doc.name}: {e}",
                    level=messages.ERROR,
                )
                continue
        self.message_user(
            request,
            "Selected documents deleted from Chroma and Django.",
            level=messages.SUCCESS,
        )


@admin.register(DocumentChunk)
class DocumentChunkAdmin(admin.ModelAdmin):
    list_display = ("document", "chunk_index", "text_hash", "created_at")
    search_fields = ("text",)
