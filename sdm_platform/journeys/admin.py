from django.contrib import admin
from django.db import models as django_models
from django.forms import Textarea

from .models import DecisionAid
from .models import Journey


@admin.register(Journey)
class JourneyAdmin(admin.ModelAdmin):
    list_display = ("title", "slug", "is_active", "sort_order")
    list_filter = ("is_active",)
    search_fields = ("title", "slug")

    fieldsets = (
        (
            "Basic Information",
            {"fields": ("slug", "title", "description")},
        ),
        (
            "Onboarding Configuration",
            {
                "fields": ("welcome_message", "onboarding_questions"),
                "description": (
                    "Configure the questions users will answer beforeentering the chat."
                ),
            },
        ),
        (
            "AI Configuration",
            {
                "fields": ("system_prompt_template",),
                "description": (
                    "The system_prompt_template can use placeholders from question IDs."
                    'E.g., if you have a question with id="duration", use {duration} '
                    "in the template."
                ),
            },
        ),
        (
            "Appearance",
            {"fields": ("hero_image", "primary_color"), "classes": ("collapse",)},
        ),
        ("Settings", {"fields": ("is_active", "sort_order")}),
    )

    formfield_overrides = {
        django_models.TextField: {"widget": Textarea(attrs={"rows": 4, "cols": 80})},
    }


@admin.register(DecisionAid)
class DecisionAidAdmin(admin.ModelAdmin):
    list_display = ["title", "slug", "aid_type", "is_active", "get_journeys_display"]
    list_filter = ["aid_type", "is_active", "journeys"]
    search_fields = ["title", "slug", "description"]
    filter_horizontal = ["journeys"]
    readonly_fields = ["created_at", "updated_at"]

    fieldsets = [
        (
            "Basic Info",
            {"fields": ["title", "slug", "aid_type", "description"]},
        ),
        (
            "Media",
            {
                "fields": ["file", "thumbnail", "external_url"],
                "description": (
                    "Upload a file for locally-hosted media, or provide an external "
                    "URL for YouTube/Vimeo embeds."
                ),
            },
        ),
        (
            "Accessibility",
            {
                "fields": ["alt_text", "transcript"],
                "classes": ["collapse"],
            },
        ),
        (
            "Context",
            {
                "fields": ["journeys", "display_context"],
                "description": (
                    "Associate with journeys and provide hints for when the LLM "
                    "should display this aid."
                ),
            },
        ),
        (
            "Lifecycle",
            {"fields": ["is_active", "sort_order", "created_at", "updated_at"]},
        ),
    ]

    formfield_overrides = {
        django_models.TextField: {"widget": Textarea(attrs={"rows": 4, "cols": 80})},
    }

    @admin.display(description="Journeys")
    def get_journeys_display(self, obj):
        if obj.is_universal:
            return "Universal (all)"
        return ", ".join(obj.journeys.values_list("slug", flat=True))
