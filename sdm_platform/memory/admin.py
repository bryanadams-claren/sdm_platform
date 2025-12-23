"""Admin interface for memory app."""

from django.contrib import admin

from sdm_platform.memory.models import ConversationPoint


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
