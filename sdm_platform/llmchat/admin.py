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
        "model_name",
        "created_at",
        "view_conversation_link",
    )
    list_filter = ("is_active", "model_name")
    search_fields = ("title", "conv_id", "thread_id", "user__username", "user__email")
    raw_id_fields = ("user",)
    readonly_fields = ("created_at", "updated_at", "view_conversation_link")

    @admin.display(description="View Conversation")
    def view_conversation_link(self, obj):
        url = reverse("chat_conversation", kwargs={"conv_id": obj.conv_id})
        return format_html('<a href="{}" target="_blank">View Conversation</a>', url)
