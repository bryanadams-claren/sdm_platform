from django import forms
from django.contrib import admin
from django.contrib import messages
from django.core.management import CommandError
from django.core.management import call_command
from django.shortcuts import redirect
from django.shortcuts import render
from django.urls import path
from django.urls import reverse

from sdm_platform.evidence.models import Document
from sdm_platform.evidence.models import DocumentChunk
from sdm_platform.journeys.models import Journey


class BulkUploadForm(forms.Form):
    journeys = forms.ModelMultipleChoiceField(
        queryset=Journey.objects.all(),
        required=False,
        widget=forms.CheckboxSelectMultiple,
        help_text="Journeys this evidence applies to. Empty = universal.",
    )


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
        "is_active",
        "processing_error",
        "processing_duration_seconds",
        "embedding_model",
        "vector_count",
        "chroma_collection",
        "processed_at",
        "uploaded_at",
        "uploaded_by",
    )
    filter_horizontal = ("journeys",)
    fieldsets = (
        (
            "Document Info",
            {"fields": ("name", "file", "content_type", "journeys")},
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
            {"fields": ("version", "is_active", "uploaded_at", "uploaded_by")},
        ),
    )
    actions = ["ingest_selected", "delete_from_chroma"]

    def get_urls(self):
        custom_urls = [
            path(
                "bulk-upload/",
                self.admin_site.admin_view(self.bulk_upload_view),
                name="evidence_document_bulk_upload",
            ),
        ]
        return custom_urls + super().get_urls()

    def changelist_view(self, request, extra_context=None):
        extra_context = extra_context or {}
        extra_context["bulk_upload_url"] = reverse(
            "admin:evidence_document_bulk_upload"
        )
        return super().changelist_view(request, extra_context=extra_context)

    def bulk_upload_view(self, request):
        if request.method == "POST":
            form = BulkUploadForm(request.POST)
            files = request.FILES.getlist("files")
            if form.is_valid() and files:
                journeys = form.cleaned_data["journeys"]
                count = 0
                for f in files:
                    doc = Document(
                        file=f,
                        name=f.name,
                        uploaded_by=request.user,
                    )
                    doc.save()
                    if journeys:
                        doc.journeys.set(journeys)
                    count += 1
                messages.success(
                    request,
                    f"Successfully uploaded {count} document(s).",
                )
                return redirect("admin:evidence_document_changelist")
            if not files:
                messages.error(request, "Please select at least one file.")
        else:
            form = BulkUploadForm()

        context = {
            **self.admin_site.each_context(request),
            "form": form,
            "opts": self.model._meta,  # noqa: SLF001 - required by Django admin templates
            "title": "Bulk Upload Documents",
        }
        return render(
            request,
            "admin/evidence/document/bulk_upload.html",
            context,
        )

    def save_model(self, request, obj, form, change):
        if not change:  # Only set on creation, not updates
            obj.uploaded_by = request.user
            # Auto-set name from filename if not provided
            if not obj.name and obj.file:
                obj.name = obj.file.name.rsplit("/", 1)[-1]
        super().save_model(request, obj, form, change)

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
