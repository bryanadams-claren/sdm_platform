"""URL configuration for memory app."""

from django.urls import path

from . import views

app_name = "memory"
urlpatterns = [
    path(
        "conversation/<str:conv_id>/points/",
        views.conversation_points_api,
        name="conversation_points",
    ),
]
