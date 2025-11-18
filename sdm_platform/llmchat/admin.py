from django.contrib import admin
from django.contrib import messages
from django.contrib.admin import ModelAdmin

from sdm_platform.llmchat.models import Conversation
from sdm_platform.llmchat.models import ConversationTemplate
from sdm_platform.users.models import User


@admin.register(Conversation)
class ConversationAdmin(ModelAdmin):
    list_display = (
        "title",
        "user",
        "template",
        "is_seed",
        "is_active",
        "model_name",
        "created_at",
    )
    list_filter = ("is_seed", "is_active", "model_name", "template")
    search_fields = ("title", "conv_id", "thread_id", "user__username", "user__email")
    raw_id_fields = ("user",)
    readonly_fields = ("created_at", "updated_at")


@admin.register(ConversationTemplate)
class ConversationTemplateAdmin(ModelAdmin):
    list_display = ("slug", "title", "is_active", "sort_order", "updated_at")
    list_filter = ("is_active",)
    search_fields = ("slug", "title", "description")
    readonly_fields = ("created_at", "updated_at")
    fieldsets = (
        ("Identity", {"fields": ("slug", "title", "description")}),
        (
            "Defaults",
            {
                "fields": (
                    "default_system_prompt",
                    "default_model_name",
                    "initial_message",
                ),
            },
        ),
        (
            "Lifecycle",
            {"fields": ("is_active", "sort_order", "created_at", "updated_at")},
        ),
    )
    actions = ["seed_for_all_users"]

    @admin.action(
        description="Ensure all users have a seed conversation for selected templates",
    )
    def seed_for_all_users(self, request, queryset):
        """
        For each selected template, ensure all users have a seed conversation.
        """
        users = (
            User.objects.all()
        )  # Keep simple; customize if you want to filter active users
        total_created = 0
        for tpl in queryset:
            for user in users.iterator():
                _, created = tpl.ensure_for_user(user)
                total_created += int(created)

        self.message_user(
            request,
            f"Seeding complete. Created {total_created} seed conversation(s).",
            level=messages.SUCCESS,
        )
