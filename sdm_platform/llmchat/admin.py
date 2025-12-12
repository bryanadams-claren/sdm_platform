from django.contrib import admin
from django.contrib.admin import ModelAdmin

from sdm_platform.llmchat.models import Conversation


@admin.register(Conversation)
class ConversationAdmin(ModelAdmin):
    list_display = (
        "title",
        "user",
        "is_active",
        "model_name",
        "created_at",
    )
    list_filter = ("is_active", "model_name")
    search_fields = ("title", "conv_id", "thread_id", "user__username", "user__email")
    raw_id_fields = ("user",)
    readonly_fields = ("created_at", "updated_at")
