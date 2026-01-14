import datetime
import json
import logging
from zoneinfo import ZoneInfo

from channels.generic.websocket import AsyncWebsocketConsumer
from django.conf import settings

from sdm_platform.llmchat.tasks import send_llm_reply
from sdm_platform.llmchat.utils.format import format_message
from sdm_platform.llmchat.utils.format import format_thread_id

logger = logging.getLogger(__name__)


def get_useremail_from_scope(scope):
    user = scope.get("user")
    return user.email if user and hasattr(user, "email") else "Anonymous"


class ChatConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        # -- set the chat room to be specific to the user
        username = get_useremail_from_scope(self.scope)
        logger.info("User with name %s connected to chat", username)
        if conv_id := (
            self.scope.get("url_route", {}).get("kwargs", {}).get("conv_id", "")
        ):
            self.thread_name = format_thread_id(username, conv_id)
        else:
            self.thread_name = format_thread_id(username, "NoThreadIDAvailable")
        await self.channel_layer.group_add(
            self.thread_name,
            self.channel_name,
        )  # Add to group to send messages later
        logger.info("Conversation opened with thread name %s", self.thread_name)
        await self.accept()

    async def disconnect(self, code):
        await self.channel_layer.group_discard(self.thread_name, self.channel_name)

    async def receive(
        self,
        text_data: str | None = None,
        bytes_data: bytes | None = None,
    ) -> None:
        if text_data is None:
            return
        text_data_json = json.loads(text_data)
        if text_data_json.get("type") == "ping":
            await self.send(text_data=json.dumps({"type": "pong"}))
        else:
            message = text_data_json["message"]
            await self.channel_layer.group_send(
                self.thread_name,
                {
                    "type": "chat.message",
                    "message": json.dumps(message),
                },
            )
            username = get_useremail_from_scope(self.scope)
            logger.info("Asking for LLM reply for thread name %s", self.thread_name)
            send_llm_reply.delay(self.thread_name, username, message)  # pyright: ignore[reportCallIssue], ignore[reportAttributeAccessIssue]

    # -- echo back the message received from the 'send' input
    async def chat_message(self, event):
        username = get_useremail_from_scope(self.scope)
        await self.send(
            text_data=json.dumps(
                format_message(
                    role="user",
                    name=username,
                    message=event["message"],
                    timestamp=datetime.datetime.now(ZoneInfo(settings.TIME_ZONE)),
                    citations=[],
                ),
            ),
        )

    # -- send along the reply from the LLM bot
    async def chat_reply(self, event):
        await self.send(
            text_data=event["content"],  # already formatted
        )


class StatusConsumer(AsyncWebsocketConsumer):
    """WebSocket consumer for AI processing status updates"""

    async def connect(self):
        """Connect to status group for the conversation"""
        username = get_useremail_from_scope(self.scope)
        if conv_id := (
            self.scope.get("url_route", {}).get("kwargs", {}).get("conv_id", "")
        ):
            self.thread_name = format_thread_id(username, conv_id)
            self.status_group = f"status_{self.thread_name}"
        else:
            self.thread_name = format_thread_id(username, "NoThreadIDAvailable")
            self.status_group = f"status_{self.thread_name}"

        await self.channel_layer.group_add(
            self.status_group,
            self.channel_name,
        )
        logger.info("Status connection opened for thread %s", self.thread_name)
        await self.accept()

    async def disconnect(self, code):
        """Disconnect from status group"""
        await self.channel_layer.group_discard(self.status_group, self.channel_name)
        logger.info("Status connection closed for thread %s", self.thread_name)

    async def receive(
        self,
        text_data: str | None = None,
        bytes_data: bytes | None = None,
    ) -> None:
        """Handle ping messages for keepalive"""
        if text_data is None:
            return
        text_data_json = json.loads(text_data)
        if text_data_json.get("type") == "ping":
            await self.send(text_data=json.dumps({"type": "pong"}))

    async def status_update(self, event):
        """Receive status updates from group and send to WebSocket"""
        await self.send(
            text_data=json.dumps(event["data"]),
        )
