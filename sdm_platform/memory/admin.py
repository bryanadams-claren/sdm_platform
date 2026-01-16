"""Admin interface for memory app."""

from django.contrib import admin

from sdm_platform.memory.models import ConversationPoint
from sdm_platform.memory.models import ConversationSummary


@admin.register(ConversationPoint)
class ConversationPointAdmin(admin.ModelAdmin):
    """
    Admin for ConversationPoint definitions.

    Note: The actual status (whether discussed) is stored in LangGraph store,
    not in Django. Use the API/views to retrieve current status.
    """

    list_display = (
        "title",
        "journey",
        "slug",
        "sort_order",
        "is_active",
    )
    list_filter = ("journey", "is_active")
    search_fields = ("title", "slug", "description")
    ordering = ("journey", "sort_order", "slug")

    fieldsets = (
        (None, {"fields": ("journey", "slug", "title", "description")}),
        ("System Message", {"fields": ("system_message_template",)}),
        (
            "Semantic Extraction",
            {
                "fields": ("semantic_keywords", "confidence_threshold"),
                "description": "Configuration for semantic memory extraction",
            },
        ),
        ("Display", {"fields": ("sort_order", "is_active")}),
    )


@admin.register(ConversationSummary)
class ConversationSummaryAdmin(admin.ModelAdmin):
    """Admin for generated conversation summaries."""

    list_display = (
        "id",
        "conversation",
        "generated_at",
    )
    list_filter = ("generated_at",)
    search_fields = ("conversation__conv_id", "conversation__user__email")
    readonly_fields = ("id", "conversation", "generated_at", "narrative_summary")
    ordering = ("-generated_at",)

    fieldsets = (
        (None, {"fields": ("id", "conversation", "generated_at")}),
        ("Content", {"fields": ("narrative_summary", "file")}),
    )

    def has_add_permission(self, request):
        """Summaries are auto-generated, not manually created."""
        return False
