from django.contrib import admin
from django.db import models as django_models
from django.forms import Textarea

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
