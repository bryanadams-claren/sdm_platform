from django.urls import path

from sdm_platform.llmchat import consumers

websocket_urlpatterns = [
    path("ws/chat/<slug:conv_id>/", consumers.ChatConsumer.as_asgi()),
]
