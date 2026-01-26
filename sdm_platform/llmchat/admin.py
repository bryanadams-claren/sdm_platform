from django.contrib import admin
from django.contrib.admin import ModelAdmin
from django.urls import reverse
from django.utils.html import format_html

from sdm_platform.llmchat.models import Conversation


@admin.register(Conversation)
class ConversationAdmin(ModelAdmin):
    list_display = (
        "title",
        "user",
        "is_active",
        "message_count",
        "last_message_at",
        "created_at",
        "view_conversation_link",
    )
    list_filter = ("is_active",)
    search_fields = ("title", "id", "user__username", "user__email")
    raw_id_fields = ("user",)
    readonly_fields = (
        "id",
        "created_at",
        "updated_at",
        "message_count",
        "last_message_at",
        "view_conversation_link",
    )

    @admin.display(description="View Conversation")
    def view_conversation_link(self, obj):
        url = reverse("conversation", kwargs={"conversation_id": obj.id})
        return format_html('<a href="{}" target="_blank">View Conversation</a>', url)
