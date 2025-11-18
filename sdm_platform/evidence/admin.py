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
        "is_processed",
        "is_active",
        "vector_count",
        "uploaded_at",
    )
    actions = ["ingest_selected", "delete_from_chroma"]

    @admin.action(
        description="Ingest selected documents into Chroma",
    )
    def ingest_selected(self, request, queryset):
        for doc in queryset:
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
