from django.urls import path

from sdm_platform.llmchat import consumers

websocket_urlpatterns = [
    path("ws/chat/<uuid:conversation_id>/", consumers.ChatConsumer.as_asgi()),
    path("ws/status/<uuid:conversation_id>/", consumers.StatusConsumer.as_asgi()),
]
