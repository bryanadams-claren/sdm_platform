"""URL configuration for memory app."""

from django.urls import path

from . import views

app_name = "memory"
urlpatterns = [
    path(
        "conversation/<uuid:conversation_id>/points/",
        views.conversation_points_api,
        name="conversation_points",
    ),
    path(
        "conversation/<uuid:conversation_id>/points/<str:point_slug>/initiate/",
        views.initiate_conversation_point,
        name="initiate_conversation_point",
    ),
    path(
        "conversation/<uuid:conversation_id>/summary/status/",
        views.conversation_summary_status,
        name="summary_status",
    ),
    path(
        "conversation/<uuid:conversation_id>/summary/download/",
        views.download_conversation_summary,
        name="download_summary",
    ),
    path(
        "conversation/<uuid:conversation_id>/summary/generate/",
        views.generate_summary_now,
        name="generate_summary",
    ),
]
