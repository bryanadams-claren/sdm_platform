from django.urls import path
from django.views.generic import RedirectView

from . import views

urlpatterns = [
    path("", RedirectView.as_view(url="/conversation/")),  #'.index, name="chat_index"),
    path("conversation/", views.conversation, name="chat_conversation_top"),
    path("conversation/<str:conv_id>/", views.conversation, name="chat_conversation"),
    path("history/<str:conv_id>/", views.history, name="chat_history"),
]
