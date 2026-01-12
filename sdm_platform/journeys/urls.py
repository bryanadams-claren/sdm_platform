from django.shortcuts import redirect
from django.urls import path

from . import views

app_name = "journeys"


def root_handler(request):
    """
    Handle root URL - either journey subdomain landing or home page.
    """
    # Check if middleware detected a journey subdomain
    if getattr(request, "journey_slug", None):
        return views.journey_subdomain_landing(request)
    # Regular home page
    return redirect("home")


urlpatterns = [
    # for subdomain handling
    path("", root_handler, name="root"),
    path(
        "start/",
        views.journey_subdomain_onboarding,
        name="journey_subdomain_onboarding",
    ),
    path(
        "not-eligible/",
        views.journey_subdomain_not_eligible,
        name="journey_subdomain_not_eligible",
    ),
    # Path-based journey access (e.g., /backpain/, /backpain/start/)
    path("<slug:journey_slug>/", views.journey_landing, name="landing"),
    path("<slug:journey_slug>/start/", views.journey_onboarding, name="onboarding"),
    path(
        "<slug:journey_slug>/not-eligible/",
        views.journey_not_eligible,
        name="not_eligible",
    ),
]
