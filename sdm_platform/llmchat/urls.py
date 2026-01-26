from django.urls import path

from . import views

urlpatterns = [
    path("conversation/", views.conversation, name="conversation_list"),
    path(
        "conversation/<uuid:conversation_id>/",
        views.conversation,
        name="conversation",
    ),
    path(
        "conversation/<uuid:conversation_id>/history/",
        views.history,
        name="conversation_history",
    ),
]
