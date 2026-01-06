import json

from allauth.account.decorators import secure_admin_login
from django.conf import settings
from django.contrib import admin
from django.contrib.auth import admin as auth_admin
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _

from sdm_platform.journeys.models import JourneyResponse
from sdm_platform.memory.managers import ConversationPointManager
from sdm_platform.memory.managers import UserProfileManager

from .forms import UserAdminChangeForm
from .forms import UserAdminCreationForm
from .models import User

if settings.DJANGO_ADMIN_FORCE_ALLAUTH:
    # Force the `admin` sign in process to go through the `django-allauth` workflow:
    # https://docs.allauth.org/en/latest/common/admin.html#admin
    admin.autodiscover()
    admin.site.login = secure_admin_login(admin.site.login)  # type: ignore[method-assign]


@admin.register(User)
class UserAdmin(auth_admin.UserAdmin):
    form = UserAdminChangeForm
    add_form = UserAdminCreationForm
    fieldsets = (
        (None, {"fields": ("email", "password")}),
        (_("Personal info"), {"fields": ("name",)}),
        (
            _("Permissions"),
            {
                "fields": (
                    "is_active",
                    "is_staff",
                    "is_superuser",
                    "groups",
                    "user_permissions",
                ),
            },
        ),
        (_("Important dates"), {"fields": ("last_login", "date_joined")}),
        (
            _("Memory Data"),
            {
                "fields": ("memory_data_display",),
                "classes": ("collapse",),  # Make it collapsible to save space
            },
        ),
    )
    readonly_fields = ["memory_data_display"]
    list_display = ["email", "name", "is_superuser"]
    search_fields = ["name"]
    ordering = ["id"]
    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": ("email", "password1", "password2"),
            },
        ),
    )

    @admin.display(description="Memory Data (JSON)")
    def memory_data_display(self, obj):
        """Display user's memory data as formatted JSON."""
        if not obj or not obj.email:
            return "No user email available"

        memory_data = {}

        # Get user profile memory
        profile = UserProfileManager.get_profile(user_id=obj.email)
        if profile:
            memory_data["profile"] = profile.model_dump(mode="json")
        else:
            memory_data["profile"] = {}

        # Get conversation point memories for all journeys
        memory_data["conversation_points"] = {}

        # Find all journeys this user has started
        journey_responses = JourneyResponse.objects.filter(user=obj).select_related(
            "journey"
        )

        for jr in journey_responses:
            journey_slug = jr.journey.slug
            cp_memories = ConversationPointManager.get_all_point_memories(
                user_id=obj.email,
                journey_slug=journey_slug,
            )

            if cp_memories:
                memory_data["conversation_points"][journey_slug] = [
                    mem.model_dump(mode="json") for mem in cp_memories
                ]

        # Format as pretty JSON
        json_str = json.dumps(memory_data, indent=2, default=str)

        # Return as HTML with syntax highlighting
        return format_html(
            '<div style="position: relative;">'
            '<button onclick="navigator.clipboard.writeText('
            "this.nextElementSibling.textContent); "
            "this.textContent='Copied!'; setTimeout(() =>"
            "this.textContent='Copy JSON', 2000);\" "
            'style="margin-bottom: 5px; padding: 5px 10px; cursor: pointer;">'
            "Copy JSON</button>"
            '<pre style="background-color: #f5f5f5; padding: 10px; '
            "border: 1px solid #ddd; border-radius: 4px; "
            'overflow-x: auto; max-height: 600px;">{}</pre>'
            "</div>",
            json_str,
        )
