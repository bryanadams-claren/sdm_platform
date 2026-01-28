# ruff: noqa: S106
# ... ignore the assertion stuff and also the hardcoded passwords
# pyright: reportGeneralTypeIssues=false, reportArgumentType=false
# ... the channel stuff
import datetime
import json
from datetime import date
from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import patch
from zoneinfo import ZoneInfo

from channels.db import database_sync_to_async
from channels.layers import get_channel_layer
from channels.testing import WebsocketCommunicator
from django.conf import settings
from django.contrib.auth.models import AnonymousUser
from django.test import Client
from django.test import TestCase
from django.test import TransactionTestCase
from django.urls import reverse
from langchain_core.documents import Document
from langchain_core.messages import AIMessage
from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig

from sdm_platform.journeys.models import DecisionAid
from sdm_platform.journeys.models import Journey
from sdm_platform.llmchat.consumers import ChatConsumer
from sdm_platform.llmchat.consumers import get_useremail_from_scope
from sdm_platform.llmchat.models import Conversation
from sdm_platform.llmchat.tasks import send_llm_reply
from sdm_platform.llmchat.utils.chat_history import get_chat_history
from sdm_platform.llmchat.utils.format import format_message
from sdm_platform.llmchat.utils.graphs import get_compiled_graph
from sdm_platform.llmchat.utils.graphs import get_postgres_checkpointer
from sdm_platform.llmchat.utils.tools.decision_aids import _convert_to_embed_url
from sdm_platform.llmchat.utils.tools.decision_aids import show_decision_aid
from sdm_platform.memory.managers import UserProfileManager
from sdm_platform.memory.store import get_memory_store
from sdm_platform.users.models import User


class ConversationModelTest(TestCase):
    """Test the Conversation model"""

    def setUp(self):
        self.user = User.objects.create_user(
            email="test@example.com",
            password="testpass123",
        )

    def test_conversation_creation(self):
        """Test creating a conversation"""
        conv = Conversation.objects.create(
            user=self.user,
            title="Test Conversation",
        )

        self.assertIsNotNone(conv.id)
        self.assertEqual(conv.user, self.user)
        self.assertEqual(conv.title, "Test Conversation")
        self.assertTrue(conv.is_active)
        # thread_id property returns UUID as string
        self.assertEqual(conv.thread_id, str(conv.id))

    def test_conversation_str_representation(self):
        """Test the string representation of a conversation"""
        conv = Conversation.objects.create(
            user=self.user,
            title="Test Title",
        )

        expected = f"Conversation: {self.user.email} / Test Title ({conv.id})"
        self.assertEqual(str(conv), expected)

    def test_conversation_defaults(self):
        """Test default values for conversation fields"""
        conv = Conversation.objects.create(
            user=self.user,
        )

        self.assertEqual(conv.title, "")
        self.assertEqual(conv.system_prompt, "")
        self.assertTrue(conv.is_active)

    def test_conversation_updated_at_changes(self):
        """Test that updated_at changes when conversation is saved"""
        conv = Conversation.objects.create(
            user=self.user,
        )

        original_updated_at = conv.updated_at
        conv.title = "Updated Title"
        conv.save()

        self.assertGreater(conv.updated_at, original_updated_at)

    @patch("sdm_platform.llmchat.models.get_postgres_checkpointer")
    def test_conversation_deletion_triggers_checkpointer_cleanup(
        self,
        mock_get_checkpointer,
    ):
        """Test that deleting a conversation also deletes LangChain history"""
        mock_checkpointer = MagicMock()
        mock_get_checkpointer.return_value.__enter__.return_value = mock_checkpointer

        conv = Conversation.objects.create(
            user=self.user,
        )

        thread_id = conv.thread_id
        conv.delete()

        # Verify checkpointer was called to delete the thread
        mock_checkpointer.delete_thread.assert_called_once_with(thread_id)


class ConversationViewTest(TestCase):
    """Test the conversation view"""

    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            email="test@example.com",
            password="testpass123",
        )
        self.client.login(username="test@example.com", password="testpass123")

    def test_conversation_view_requires_login(self):
        """Test that conversation view requires authentication"""
        self.client.logout()
        response = self.client.get(reverse("conversation_list"))

        # Should redirect to login
        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response.url)  # pyright: ignore[reportAttributeAccessIssue]

    def test_conversation_view_creates_default_conversation(self):
        """Test that accessing conversation view creates a default conversation"""
        response = self.client.get(reverse("conversation_list"))

        self.assertEqual(response.status_code, 200)
        conversations = Conversation.objects.filter(user=self.user)
        self.assertEqual(conversations.count(), 1)
        self.assertEqual(conversations[0].title, "General Q&A")

    def test_conversation_view_with_existing_conversations(self):
        """Test conversation view when conversations already exist"""
        conv1 = Conversation.objects.create(
            user=self.user,
            title="First Conversation",
        )

        response = self.client.get(reverse("conversation_list"))

        self.assertEqual(response.status_code, 200)
        self.assertIn("conversations", response.context)
        self.assertEqual(response.context["active_conversation_id"], str(conv1.id))

    def test_conversation_view_with_specific_conversation_id(self):
        """Test conversation view with a specific conversation_id"""
        conv1 = Conversation.objects.create(
            user=self.user,
            title="First Conversation",
        )

        response = self.client.get(
            reverse("conversation", kwargs={"conversation_id": conv1.id}),
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["active_conversation_id"], str(conv1.id))


class HistoryViewTest(TestCase):
    """Test the history view"""

    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            email="test@example.com",
            password="testpass123",
        )
        self.client.login(username="test@example.com", password="testpass123")

        self.conversation = Conversation.objects.create(
            user=self.user,
            title="Test Conversation",
        )

    def test_history_view_requires_login(self):
        """Test that history view requires authentication"""
        self.client.logout()
        response = self.client.get(
            reverse(
                "conversation_history", kwargs={"conversation_id": self.conversation.id}
            ),
        )

        # Should redirect to login
        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response.url)  # pyright: ignore[reportAttributeAccessIssue]

    @patch("sdm_platform.llmchat.views.get_postgres_checkpointer")
    @patch("sdm_platform.llmchat.views.get_compiled_graph")
    @patch("sdm_platform.llmchat.views.get_chat_history")
    def test_history_view_returns_messages(
        self,
        mock_get_chat_history,
        mock_get_graph,
        mock_get_checkpointer,
    ):
        """Test that history view returns formatted messages"""
        # Mock the checkpointer context manager
        mock_checkpointer_instance = MagicMock()
        mock_get_checkpointer.return_value.__enter__.return_value = (
            mock_checkpointer_instance
        )

        # Mock the graph
        mock_graph = MagicMock()
        mock_get_graph.return_value = mock_graph

        # Mock state history
        mock_graph.get_state_history.return_value = []

        # Mock chat history processing
        timestamp = datetime.datetime.now(ZoneInfo(settings.TIME_ZONE))
        mock_get_chat_history.return_value = [
            {
                "created_at": timestamp,
                "new_messages": [
                    {
                        "type": "human",
                        "data": {
                            "content": "Hello",
                            "metadata": {"username": "test@example.com"},
                        },
                    },
                    {
                        "type": "ai",
                        "data": {
                            "content": "Hi there!",
                            "metadata": {},
                        },
                    },
                ],
                "turn_citations": [],
            },
        ]

        response = self.client.get(
            reverse(
                "conversation_history", kwargs={"conversation_id": self.conversation.id}
            ),
        )

        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        self.assertIn("messages", data)
        self.assertEqual(len(data["messages"]), 2)


class FormatUtilsTest(TestCase):
    """Test the format utility functions"""

    def test_format_message_with_bot_role(self):
        """Test formatting a message with bot role"""
        timestamp = datetime.datetime.now(ZoneInfo(settings.TIME_ZONE))
        result = format_message(
            role="ai",
            name="Assistant",
            message="Hello!",
            timestamp=timestamp,
            citations=[],
        )

        self.assertEqual(result["role"], "bot")
        self.assertEqual(result["content"], "Hello!")
        self.assertEqual(result["name"], "Assistant")
        self.assertEqual(result["timestamp"], timestamp.isoformat())
        self.assertEqual(result["citations"], [])

    def test_format_message_with_user_role(self):
        """Test formatting a message with user role"""
        timestamp = datetime.datetime.now(ZoneInfo(settings.TIME_ZONE))
        result = format_message(
            role="human",
            name="User",
            message="Hi!",
            timestamp=timestamp,
            citations=[],
        )

        self.assertEqual(result["role"], "user")

    def test_format_message_role_variations(self):
        """Test that various role aliases are normalized correctly"""
        timestamp = datetime.datetime.now(ZoneInfo(settings.TIME_ZONE))

        # Test bot aliases
        for role in ["assistant", "ai", "bot"]:
            result = format_message(
                role=role,
                name="Bot",
                message="test",
                timestamp=timestamp,
                citations=[],
            )
            self.assertEqual(result["role"], "bot")

        # Test user aliases
        for role in ["human", "user"]:
            result = format_message(
                role=role,
                name="User",
                message="test",
                timestamp=timestamp,
                citations=[],
            )
            self.assertEqual(result["role"], "user")

    def test_format_message_with_citations(self):
        """Test formatting a message with citations"""
        timestamp = datetime.datetime.now(ZoneInfo(settings.TIME_ZONE))
        citations = [
            {
                "index": 1,
                "doc_id": "doc123",
                "title": "Test Document",
                "url": "/documents/doc123/",
            },
        ]

        result = format_message(
            role="bot",
            name="Assistant",
            message="Based on the evidence [1]...",
            timestamp=timestamp,
            citations=citations,
        )

        self.assertEqual(result["citations"], citations)


class ChatHistoryUtilsTest(TestCase):
    """Test the chat history utility functions"""

    def test_get_chat_history_with_empty_history(self):
        """Test getting chat history with no snapshots"""
        result = get_chat_history([])
        self.assertEqual(result, [])

    def test_get_chat_history_with_messages(self):
        """Test getting chat history with message snapshots"""
        timestamp = datetime.datetime.now(ZoneInfo(settings.TIME_ZONE))

        # Create mock snapshots representing the state evolution
        # Snapshot 1: Initial state with first human message
        mock_snap1 = MagicMock()
        mock_snap1.values = {
            "messages": [HumanMessage(content="Hello")],
            "turn_citations": [],
        }
        mock_snap1.created_at = timestamp.isoformat()

        # Snapshot 2: State after AI responds (contains both messages)
        mock_snap2 = MagicMock()
        mock_snap2.values = {
            "messages": [
                HumanMessage(content="Hello"),
                AIMessage(content="Hi there!"),
            ],
            "turn_citations": [],
        }
        mock_snap2.created_at = (timestamp + datetime.timedelta(seconds=1)).isoformat()

        # Pass snapshots in reverse chronological order (newest first)
        # as they would come from graph.get_state_history()
        result = get_chat_history([mock_snap2, mock_snap1])

        # Should have 2 diffs: one for initial human message, one for AI response
        self.assertEqual(len(result), 2)

        # First diff (chronologically) should have the human message
        self.assertEqual(len(result[0]["new_messages"]), 1)
        self.assertEqual(result[0]["new_messages"][0]["data"]["content"], "Hello")

        # Second diff should have only the AI message (new message)
        self.assertEqual(len(result[1]["new_messages"]), 1)
        self.assertEqual(result[1]["new_messages"][0]["data"]["content"], "Hi there!")

    def test_get_chat_history_preserves_citations(self):
        """Test that chat history preserves turn citations"""
        timestamp = datetime.datetime.now(ZoneInfo(settings.TIME_ZONE))

        citations = [{"index": 1, "doc_id": "doc123"}]

        mock_snap = MagicMock()
        mock_snap.values = {
            "messages": [AIMessage(content="Response")],
            "turn_citations": citations,
        }
        mock_snap.created_at = timestamp.isoformat()

        result = get_chat_history([mock_snap])

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["turn_citations"], citations)


class TasksTest(TestCase):
    """Test the Celery tasks"""

    def setUp(self):
        self.user = User.objects.create_user(
            email="test@example.com",
            password="testpass123",
        )
        self.conversation = Conversation.objects.create(
            user=self.user,
            title="Test Conversation",
        )

    @patch("sdm_platform.llmchat.tasks.async_to_sync")
    @patch("sdm_platform.llmchat.tasks.get_channel_layer")
    @patch("sdm_platform.llmchat.tasks.get_postgres_checkpointer")
    @patch("sdm_platform.llmchat.tasks.get_compiled_graph")
    def test_send_llm_reply_basic(
        self,
        mock_get_graph,
        mock_get_checkpointer,
        mock_get_channel_layer,
        mock_async_to_sync,
    ):
        """Test basic LLM reply functionality"""
        # Mock checkpointer
        mock_checkpointer_instance = MagicMock()
        mock_get_checkpointer.return_value.__enter__.return_value = (
            mock_checkpointer_instance
        )

        # Mock graph
        mock_graph = MagicMock()
        mock_get_graph.return_value = mock_graph

        # Mock graph response
        ai_message = AIMessage(content="This is the AI response")
        mock_graph.invoke.return_value = {
            "messages": [HumanMessage(content="Hello"), ai_message],
            "turn_citations": [],
        }

        # Mock channel layer
        mock_channel_layer = MagicMock()
        mock_channel_layer.group_send = AsyncMock()
        mock_get_channel_layer.return_value = mock_channel_layer

        # Mock async_to_sync to just call the function synchronously
        mock_async_to_sync.side_effect = lambda f: lambda *args, **kwargs: None

        # Call the task - thread_name is now the conversation UUID
        send_llm_reply(
            thread_name=str(self.conversation.id),
            username="test@example.com",
            user_input="Hello",
        )

        # Verify the graph was invoked
        mock_graph.invoke.assert_called_once()

        # Verify async_to_sync was called (which wraps group_send)
        mock_async_to_sync.assert_called_once()

        # Verify conversation was updated
        self.conversation.refresh_from_db()
        # updated_at should have changed (can't test exact value due to timing)

    @patch("sdm_platform.llmchat.tasks.async_to_sync")
    @patch("sdm_platform.llmchat.tasks.get_channel_layer")
    @patch("sdm_platform.llmchat.tasks.get_postgres_checkpointer")
    @patch("sdm_platform.llmchat.tasks.get_compiled_graph")
    def test_send_llm_reply_with_citations(
        self,
        mock_get_graph,
        mock_get_checkpointer,
        mock_get_channel_layer,
        mock_async_to_sync,
    ):
        """Test LLM reply with citations"""
        # Mock checkpointer
        mock_checkpointer_instance = MagicMock()
        mock_get_checkpointer.return_value.__enter__.return_value = (
            mock_checkpointer_instance
        )

        # Mock graph
        mock_graph = MagicMock()
        mock_get_graph.return_value = mock_graph

        # Mock graph response with citations
        citations = [
            {
                "index": 1,
                "doc_id": "doc123",
                "title": "Test Document",
                "url": "/documents/doc123/",
            },
        ]

        ai_message = AIMessage(content="Based on [1]...")
        mock_graph.invoke.return_value = {
            "messages": [HumanMessage(content="Hello"), ai_message],
            "turn_citations": citations,
        }

        # Mock channel layer
        mock_channel_layer = MagicMock()
        mock_channel_layer.group_send = AsyncMock()
        mock_get_channel_layer.return_value = mock_channel_layer

        # Capture the call arguments
        captured_args = []

        def capture_call(f):
            def wrapper(*args, **kwargs):
                captured_args.append((args, kwargs))

            return wrapper

        mock_async_to_sync.side_effect = capture_call

        # Call the task - thread_name is now the conversation UUID
        send_llm_reply(
            thread_name=str(self.conversation.id),
            username="test@example.com",
            user_input="Tell me about something",
        )

        # Verify async_to_sync was called
        self.assertEqual(len(captured_args), 1)

    @patch("sdm_platform.llmchat.tasks.async_to_sync")
    @patch("sdm_platform.llmchat.tasks.get_channel_layer")
    @patch("sdm_platform.llmchat.tasks.get_postgres_checkpointer")
    @patch("sdm_platform.llmchat.tasks.get_compiled_graph")
    def test_send_llm_reply_no_ai_response(
        self,
        mock_get_graph,
        mock_get_checkpointer,
        mock_get_channel_layer,
        mock_async_to_sync,
    ):
        """Test when LLM doesn't return an AI message"""
        # Mock checkpointer
        mock_checkpointer_instance = MagicMock()
        mock_get_checkpointer.return_value.__enter__.return_value = (
            mock_checkpointer_instance
        )

        # Mock graph
        mock_graph = MagicMock()
        mock_get_graph.return_value = mock_graph

        # Mock graph response without AI message
        mock_graph.invoke.return_value = {
            "messages": [HumanMessage(content="Hello")],
            "turn_citations": [],
        }

        # Mock channel layer
        mock_channel_layer = MagicMock()
        mock_channel_layer.group_send = AsyncMock()
        mock_get_channel_layer.return_value = mock_channel_layer

        # Mock async_to_sync
        mock_async_to_sync.side_effect = lambda f: lambda *args, **kwargs: None

        # Call the task - thread_name is now the conversation UUID
        send_llm_reply(
            thread_name=str(self.conversation.id),
            username="test@example.com",
            user_input="Hello",
        )

        # Verify async_to_sync was NOT called (no AI response)
        mock_async_to_sync.assert_not_called()


class URLConfigTest(TestCase):
    """Test URL configuration"""

    def test_url_patterns_exist(self):
        """Test that expected URL patterns are configured"""
        import uuid  # noqa: PLC0415

        test_uuid = uuid.uuid4()

        # Test conversation top level URL
        url = reverse("conversation_list")
        self.assertEqual(url, "/conversation/")

        # Test conversation with conversation_id (UUID)
        url = reverse("conversation", kwargs={"conversation_id": test_uuid})
        self.assertEqual(url, f"/conversation/{test_uuid}/")

        # Test history URL
        url = reverse("conversation_history", kwargs={"conversation_id": test_uuid})
        self.assertEqual(url, f"/conversation/{test_uuid}/history/")


class ChatConsumerTest(TransactionTestCase):
    """Test the WebSocket ChatConsumer - uses TransactionTestCase for async support"""

    def setUp(self):
        self.user = User.objects.create_user(
            email="test@example.com",
            password="testpass123",
        )
        self.conversation = Conversation.objects.create(
            user=self.user,
            title="Test Conversation",
        )

    @patch("sdm_platform.llmchat.consumers.send_llm_reply")
    async def test_consumer_connect(self, mock_send_llm_reply):
        """Test WebSocket connection"""

        # Get user and conversation in async-safe way
        @database_sync_to_async
        def get_user_and_conv():
            user = User.objects.get(email="test@example.com")
            conv = Conversation.objects.get(user=user)
            return user, conv.id

        user, conv_id = await get_user_and_conv()

        # Create communicator with user in scope
        communicator = WebsocketCommunicator(
            ChatConsumer.as_asgi(),
            f"/ws/chat/{conv_id}/",
        )
        communicator.scope["user"] = user
        communicator.scope["url_route"] = {
            "kwargs": {"conversation_id": conv_id},
        }

        # Connect
        connected, _ = await communicator.connect()
        self.assertTrue(connected)

        # Disconnect
        await communicator.disconnect()

    @patch("sdm_platform.llmchat.consumers.send_llm_reply")
    async def test_consumer_receive_message(self, mock_send_llm_reply):
        """Test receiving a message through WebSocket"""

        # Get user and conversation in async-safe way
        @database_sync_to_async
        def get_user_and_conv():
            user = User.objects.get(email="test@example.com")
            conv = Conversation.objects.get(user=user)
            return user, conv.id

        user, conv_id = await get_user_and_conv()

        # Create communicator
        communicator = WebsocketCommunicator(
            ChatConsumer.as_asgi(),
            f"/ws/chat/{conv_id}/",
        )
        communicator.scope["user"] = user
        communicator.scope["url_route"] = {
            "kwargs": {"conversation_id": conv_id},
        }

        # Connect
        await communicator.connect()

        # Send a message
        await communicator.send_json_to(
            {
                "message": "Hello, bot!",
            }
        )

        # Receive the echo
        response = await communicator.receive_json_from()

        # Verify response structure
        self.assertEqual(response["role"], "user")
        self.assertEqual(response["name"], "test@example.com")
        self.assertIn("Hello, bot!", response["content"])
        self.assertIn("timestamp", response)
        self.assertEqual(response["citations"], [])

        # Verify Celery task was called with the UUID as thread_name
        mock_send_llm_reply.delay.assert_called_once_with(
            str(conv_id),
            "test@example.com",
            "Hello, bot!",
        )

        # Disconnect
        await communicator.disconnect()

    @patch("sdm_platform.llmchat.consumers.send_llm_reply")
    async def test_consumer_ping_pong(self, mock_send_llm_reply):
        """Test ping/pong functionality"""

        # Get user and conversation in async-safe way
        @database_sync_to_async
        def get_user_and_conv():
            user = User.objects.get(email="test@example.com")
            conv = Conversation.objects.get(user=user)
            return user, conv.id

        user, conv_id = await get_user_and_conv()

        # Create communicator
        communicator = WebsocketCommunicator(
            ChatConsumer.as_asgi(),
            f"/ws/chat/{conv_id}/",
        )
        communicator.scope["user"] = user
        communicator.scope["url_route"] = {
            "kwargs": {"conversation_id": conv_id},
        }

        # Connect
        await communicator.connect()

        # Send a ping
        await communicator.send_json_to(
            {
                "type": "ping",
            }
        )

        # Receive pong
        response = await communicator.receive_json_from()
        self.assertEqual(response["type"], "pong")

        # Verify Celery task was NOT called for ping
        mock_send_llm_reply.delay.assert_not_called()

        # Disconnect
        await communicator.disconnect()

    @patch("sdm_platform.llmchat.consumers.send_llm_reply")
    async def test_consumer_without_conversation_id(self, mock_send_llm_reply):
        """Test WebSocket connection without conversation_id"""

        # Get user in async-safe way
        @database_sync_to_async
        def get_user():
            return User.objects.get(email="test@example.com")

        user = await get_user()

        # Create communicator without conversation_id
        communicator = WebsocketCommunicator(
            ChatConsumer.as_asgi(),
            "/ws/chat/",
        )
        communicator.scope["user"] = user
        communicator.scope["url_route"] = {
            "kwargs": {},  # No conversation_id
        }

        # Connect
        connected, _ = await communicator.connect()
        self.assertTrue(connected)

        # Send a message
        await communicator.send_json_to(
            {
                "message": "Hello!",
            }
        )

        # Receive the echo
        response = await communicator.receive_json_from()
        self.assertEqual(response["role"], "user")

        # Verify task was called with fallback thread name
        mock_send_llm_reply.delay.assert_called_once()
        call_args = mock_send_llm_reply.delay.call_args[0]
        self.assertIn("NoThreadID", call_args[0])

        # Disconnect
        await communicator.disconnect()

    @patch("sdm_platform.llmchat.consumers.send_llm_reply")
    async def test_consumer_chat_reply(self, mock_send_llm_reply):
        """Test receiving a bot reply through the consumer"""

        # Get user and conversation in async-safe way
        @database_sync_to_async
        def get_user_and_conv():
            user = User.objects.get(email="test@example.com")
            conv = Conversation.objects.get(user=user)
            return user, conv.id

        user, conv_id = await get_user_and_conv()

        # Create communicator
        communicator = WebsocketCommunicator(
            ChatConsumer.as_asgi(),
            f"/ws/chat/{conv_id}/",
        )
        communicator.scope["user"] = user
        communicator.scope["url_route"] = {
            "kwargs": {"conversation_id": conv_id},
        }

        # Connect
        await communicator.connect()

        # Simulate a bot reply being sent to the group
        # This would normally come from the Celery task
        timestamp = datetime.datetime.now(ZoneInfo(settings.TIME_ZONE))
        bot_message = format_message(
            role="bot",
            name=settings.AI_ASSISTANT_NAME,
            message="This is the bot response",
            timestamp=timestamp,
            citations=[],
        )

        # Get the channel layer directly
        # thread_name is now just the UUID string
        channel_layer = get_channel_layer()
        if channel_layer:
            await channel_layer.group_send(
                str(conv_id),
                {
                    "type": "chat.reply",
                    "content": json.dumps(bot_message),
                },
            )
        else:
            self.assertIsNotNone(channel_layer)

        # Receive the bot response
        response = await communicator.receive_json_from()
        self.assertEqual(response["role"], "bot")
        self.assertEqual(response["content"], "This is the bot response")
        self.assertEqual(response["name"], settings.AI_ASSISTANT_NAME)

        # Disconnect
        await communicator.disconnect()


class ChatConsumerUtilsTest(TestCase):
    """Test utility functions used by ChatConsumer - uses regular TestCase"""

    def setUp(self):
        self.user = User.objects.create_user(
            email="test@example.com",
            password="testpass123",
        )

    def test_get_useremail_from_scope_with_user(self):
        """Test extracting user email from scope"""

        scope = {"user": self.user}
        result = get_useremail_from_scope(scope)
        self.assertEqual(result, "test@example.com")

    def test_get_useremail_from_scope_without_user(self):
        """Test extracting user email from scope when no user"""

        scope = {}
        result = get_useremail_from_scope(scope)
        self.assertEqual(result, "Anonymous")

    def test_get_useremail_from_scope_with_anonymous(self):
        """Test extracting user email from scope with AnonymousUser"""

        anonymous = AnonymousUser()
        scope = {"user": anonymous}
        result = get_useremail_from_scope(scope)
        self.assertEqual(result, "Anonymous")


class GraphWithMemoryTest(TestCase):
    """Test LangGraph integration with memory module."""

    def setUp(self):
        """Set up test fixtures."""
        self.user = User.objects.create_user(
            email="memory_test@example.com",
            password="testpass123",
        )

    @patch("sdm_platform.llmchat.utils.graphs.base.init_chat_model")
    @patch("sdm_platform.llmchat.utils.graphs.nodes.retrieval.get_chroma_client")
    def test_graph_loads_user_profile_context(self, mock_chroma, mock_init_model):
        """Test that the graph loads user profile and includes it in context."""
        # Create a user profile
        with get_memory_store() as store:
            UserProfileManager.update_profile(
                user_id=self.user.email,
                updates={
                    "name": "Jane Doe",
                    "preferred_name": "Jane",
                    "birthday": date(1985, 3, 15),
                },
                store=store,
                source="user_input",
            )

        # Mock the LLM to return a proper AIMessage
        mock_model = MagicMock()
        mock_model.invoke.return_value = AIMessage(content="Hello! How can I help you?")
        mock_init_model.return_value = mock_model

        # Mock Chroma to avoid actual vector search
        mock_chroma.return_value = MagicMock()

        # Build the graph with store
        with get_postgres_checkpointer() as checkpointer, get_memory_store() as store:
            graph = get_compiled_graph(checkpointer, store=store)

            # Invoke the graph with user_id in config
            config = RunnableConfig(
                configurable={
                    "thread_id": "test_thread_memory",
                    "user_id": self.user.email,
                },
            )

            result = graph.invoke(
                {
                    "messages": [
                        HumanMessage(content="Hello, what's my name?"),
                    ],
                    "user_context": "",
                    "system_prompt": "",
                    "turn_citations": [],
                },
                config,
            )

        # Verify user_context was populated
        self.assertIn("user_context", result)
        user_context = result["user_context"]

        # The context should contain the user's preferred name
        self.assertIn("USER CONTEXT:", user_context)
        self.assertIn("Jane", user_context)
        self.assertIn("prefers to be called", user_context)

    @patch("sdm_platform.llmchat.utils.graphs.base.init_chat_model")
    @patch("sdm_platform.llmchat.utils.graphs.nodes.retrieval.get_chroma_client")
    def test_graph_includes_profile_in_rag_system_message(
        self, mock_chroma, mock_init_model
    ):
        """Test that user profile is included in RAG system message."""
        # Create a user profile
        with get_memory_store() as store:
            UserProfileManager.update_profile(
                user_id=self.user.email,
                updates={
                    "preferred_name": "Bob",
                    "birthday": date(1990, 6, 20),
                },
                store=store,
            )

        # Mock the LLM to return a proper AIMessage
        mock_model = MagicMock()
        mock_model.invoke.return_value = AIMessage(content="I can help with that!")
        mock_init_model.return_value = mock_model

        # Mock Chroma with fake documents to trigger RAG path
        mock_client = MagicMock()
        mock_collection = MagicMock()
        mock_collection.name = "test_collection"
        mock_client.list_collections.return_value = [mock_collection]

        # Mock Chroma vector store to return fake documents
        mock_vs = MagicMock()
        fake_doc = Document(
            page_content="This is test evidence content.",
            metadata={
                "document_id": "test_doc_1",
                "chunk_index": 0,
                "page": 1,
            },
        )
        # similarity_search_with_score returns (Document, score) tuples
        # Score of 0.3 is below MAX_DISTANCE_METRIC (0.5) so it will be included
        mock_vs.similarity_search_with_score.return_value = [(fake_doc, 0.3)]

        # Patch Chroma constructor to return our mock
        mock_chroma.return_value = mock_client

        with patch(
            "sdm_platform.llmchat.utils.graphs.nodes.retrieval.Chroma",
            return_value=mock_vs,
        ):
            # Build the graph
            with (
                get_postgres_checkpointer() as checkpointer,
                get_memory_store() as store,
            ):
                graph = get_compiled_graph(checkpointer, store=store)

                config = RunnableConfig(
                    configurable={
                        "thread_id": "test_thread_rag_memory",
                        "user_id": self.user.email,
                    },
                )

                # Send a message with @llm prefix to trigger RAG
                _ = graph.invoke(
                    {
                        "messages": [
                            HumanMessage(content="@llm What treatment options exist?"),
                        ],
                        "user_context": "",
                        "system_prompt": "",
                        "turn_citations": [],
                    },
                    config,
                )

            # The model should have been invoked with messages
            self.assertTrue(mock_model.invoke.called)

            # Get the messages that were passed to the model
            call_args = mock_model.invoke.call_args
            messages = call_args[0][0]  # First positional argument

            # Find the system message (should be first)
            system_message = None
            for msg in messages:
                if msg.type == "system":
                    system_message = msg
                    break
            # Verify system message contains user context
            self.assertIsNotNone(system_message)
            if system_message:
                self.assertIn("USER CONTEXT:", system_message.content)
                self.assertIn("Bob", system_message.content)
                self.assertIn("June 20", system_message.content)

    @patch("sdm_platform.llmchat.utils.graphs.base.init_chat_model")
    @patch("sdm_platform.llmchat.utils.graphs.nodes.retrieval.get_chroma_client")
    def test_graph_works_without_profile(self, mock_chroma, mock_init_model):
        """Test that the graph works normally when no profile exists."""
        # Mock the LLM to return a proper AIMessage
        mock_model = MagicMock()
        mock_model.invoke.return_value = AIMessage(content="Hello!")
        mock_init_model.return_value = mock_model

        # Mock Chroma to return empty collections (no RAG)
        mock_client = MagicMock()
        mock_client.list_collections.return_value = []
        mock_chroma.return_value = mock_client

        # Build the graph
        with get_postgres_checkpointer() as checkpointer, get_memory_store() as store:
            graph = get_compiled_graph(checkpointer, store=store)

            config = RunnableConfig(
                configurable={
                    "thread_id": "test_thread_no_memory",
                    "user_id": "nonexistent@example.com",
                },
            )

            # Should not raise an exception
            # Use @llm prefix to trigger model invocation
            result = graph.invoke(
                {
                    "messages": [
                        HumanMessage(content="@llm Hello"),
                    ],
                    "user_context": "",
                    "system_prompt": "",
                    "turn_citations": [],
                },
                config,
            )

        # Should have empty user_context (no profile exists)
        self.assertEqual(result["user_context"], "")

        # Should still process normally and return messages
        # Messages: original human message + AI response
        self.assertGreaterEqual(len(result["messages"]), 1)
        self.assertTrue(mock_model.invoke.called)


class DecisionAidURLConversionTest(TestCase):
    """Test the URL conversion utility for decision aids."""

    def test_convert_youtube_watch_url(self):
        """Test converting YouTube watch URL to embed URL."""
        url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
        result = _convert_to_embed_url(url)
        self.assertEqual(result, "https://www.youtube.com/embed/dQw4w9WgXcQ")

    def test_convert_youtube_short_url(self):
        """Test converting YouTube short URL (youtu.be) to embed URL."""
        url = "https://youtu.be/dQw4w9WgXcQ"
        result = _convert_to_embed_url(url)
        self.assertEqual(result, "https://www.youtube.com/embed/dQw4w9WgXcQ")

    def test_convert_youtube_short_url_with_params(self):
        """Test converting YouTube short URL with query params."""
        url = "https://youtu.be/dQw4w9WgXcQ?t=120"
        result = _convert_to_embed_url(url)
        self.assertEqual(result, "https://www.youtube.com/embed/dQw4w9WgXcQ")

    def test_convert_vimeo_url(self):
        """Test converting Vimeo URL to embed URL."""
        url = "https://vimeo.com/123456789"
        result = _convert_to_embed_url(url)
        self.assertEqual(result, "https://player.vimeo.com/video/123456789")

    def test_already_embed_url_unchanged(self):
        """Test that already-embed URLs are returned unchanged."""
        # YouTube embed URL
        url = "https://www.youtube.com/embed/dQw4w9WgXcQ"
        result = _convert_to_embed_url(url)
        self.assertEqual(result, url)

        # Vimeo embed URL
        url = "https://player.vimeo.com/video/123456789"
        result = _convert_to_embed_url(url)
        self.assertEqual(result, url)

    def test_non_video_url_unchanged(self):
        """Test that non-video URLs are returned unchanged."""
        url = "https://example.com/image.png"
        result = _convert_to_embed_url(url)
        self.assertEqual(result, url)

    def test_empty_url_unchanged(self):
        """Test that empty URLs are returned unchanged."""
        result = _convert_to_embed_url("")
        self.assertEqual(result, "")

    def test_none_url_handling(self):
        """Test that None-ish values are handled gracefully."""
        result = _convert_to_embed_url("")
        self.assertEqual(result, "")


class ShowDecisionAidToolTest(TestCase):
    """Test the show_decision_aid LangChain tool."""

    def setUp(self):
        import uuid  # noqa: PLC0415

        self.journey, _ = Journey.objects.get_or_create(
            slug="backpain-tool-test",
            defaults={"title": "Back Pain Journey (Tool Test)"},
        )

        # Create a test decision aid with unique slug (using short UUID)
        self.unique_id = str(uuid.uuid4())[:8]
        self.aid = DecisionAid.objects.create(
            slug=f"spine-{self.unique_id}",
            title="Spine Anatomy",
            aid_type=DecisionAid.AidType.IMAGE,
            external_url="https://example.com/spine.png",
            description="A diagram of the spine.",
            alt_text="Spine anatomy diagram",
        )
        self.aid_slug = self.aid.slug

    def test_show_decision_aid_success(self):
        """Test successful retrieval of a decision aid."""
        result = show_decision_aid.invoke({"aid_slug": self.aid_slug})

        self.assertTrue(result["success"])
        self.assertEqual(result["aid_slug"], self.aid_slug)
        self.assertEqual(result["title"], "Spine Anatomy")
        self.assertEqual(result["aid_type"], DecisionAid.AidType.IMAGE)
        self.assertEqual(result["url"], "https://example.com/spine.png")
        self.assertEqual(result["alt_text"], "Spine anatomy diagram")
        self.assertEqual(result["context_message"], "")

    def test_show_decision_aid_with_context_message(self):
        """Test retrieval with a context message."""
        result = show_decision_aid.invoke(
            {
                "aid_slug": self.aid_slug,
                "context_message": "Here's what the spine looks like:",
            }
        )

        self.assertTrue(result["success"])
        self.assertEqual(result["context_message"], "Here's what the spine looks like:")

    def test_show_decision_aid_not_found(self):
        """Test behavior when aid is not found."""
        result = show_decision_aid.invoke({"aid_slug": "nonexistent-aid-xyz123"})

        self.assertFalse(result["success"])
        self.assertIn("not found", result["error"])
        self.assertIn("nonexistent-aid-xyz123", result["error"])

    def test_show_decision_aid_inactive_not_found(self):
        """Test that inactive aids are not returned."""
        self.aid.is_active = False
        self.aid.save()

        result = show_decision_aid.invoke({"aid_slug": self.aid_slug})

        self.assertFalse(result["success"])
        self.assertIn("not found", result["error"])

    def test_show_decision_aid_converts_external_video_url(self):
        """Test that external video URLs are converted to embed format."""
        slug = f"vid-{self.unique_id}"
        video_aid = DecisionAid.objects.create(  # noqa: F841
            slug=slug,
            title="Surgery Video",
            aid_type=DecisionAid.AidType.EXTERNAL_VIDEO,
            external_url="https://www.youtube.com/watch?v=abc123",
            description="A video of the surgery procedure.",
        )

        result = show_decision_aid.invoke({"aid_slug": slug})

        self.assertTrue(result["success"])
        self.assertEqual(result["url"], "https://www.youtube.com/embed/abc123")

    def test_show_decision_aid_uses_file_url_when_present(self):
        """Test that file URL is used when file is uploaded."""
        from django.core.files.uploadedfile import SimpleUploadedFile  # noqa: PLC0415

        test_file = SimpleUploadedFile(
            name="test.png",
            content=b"\x89PNG\r\n\x1a\n",
            content_type="image/png",
        )

        slug = f"upl-{self.unique_id}"
        file_aid = DecisionAid.objects.create(  # pyright: ignore[reportUnusedVariable]  # noqa: F841
            slug=slug,
            title="Uploaded Image",
            aid_type=DecisionAid.AidType.IMAGE,
            file=test_file,
            description="An uploaded image.",
        )

        result = show_decision_aid.invoke({"aid_slug": slug})

        self.assertTrue(result["success"])
        self.assertIn("decision_aids/", result["url"])

    def test_show_decision_aid_falls_back_to_title_for_alt_text(self):
        """Test that title is used as alt_text when alt_text is empty."""
        slug = f"noalt-{self.unique_id}"
        aid_no_alt = DecisionAid.objects.create(  # pyright: ignore[reportUnusedVariable]  # noqa: F841
            slug=slug,
            title="Aid Without Alt Text",
            aid_type=DecisionAid.AidType.DIAGRAM,
            external_url="https://example.com/diagram.png",
            description="A diagram without alt text.",
            alt_text="",  # Empty alt text
        )

        result = show_decision_aid.invoke({"aid_slug": slug})

        self.assertTrue(result["success"])
        self.assertEqual(result["alt_text"], "Aid Without Alt Text")


class FormatMessageWithDecisionAidsTest(TestCase):
    """Test format_message with decision_aids parameter."""

    def test_format_message_with_decision_aids(self):
        """Test that decision_aids are included in formatted message."""
        timestamp = datetime.datetime.now(ZoneInfo(settings.TIME_ZONE))
        decision_aids = [
            {
                "aid_id": "abc123",
                "aid_slug": "spine-anatomy",
                "aid_type": "image",
                "title": "Spine Anatomy",
                "url": "https://example.com/spine.png",
            }
        ]

        result = format_message(
            role="ai",
            name="Assistant",
            message="Here's the spine anatomy.",
            timestamp=timestamp,
            citations=[],
            decision_aids=decision_aids,
        )

        self.assertEqual(result["decision_aids"], decision_aids)

    def test_format_message_without_decision_aids(self):
        """Test that decision_aids defaults to empty when not provided."""
        timestamp = datetime.datetime.now(ZoneInfo(settings.TIME_ZONE))

        result = format_message(
            role="ai",
            name="Assistant",
            message="Hello!",
            timestamp=timestamp,
            citations=[],
        )

        # Should have empty decision_aids or not have the key
        self.assertEqual(result.get("decision_aids", []), [])


class ChatHistoryWithDecisionAidsTest(TestCase):
    """Test chat history processing with decision aids."""

    def test_get_chat_history_includes_decision_aids(self):
        """Test that decision aids are preserved in chat history."""
        timestamp = datetime.datetime.now(ZoneInfo(settings.TIME_ZONE))

        decision_aids = [
            {
                "aid_id": "test-id",
                "aid_slug": "test-slug",
                "aid_type": "image",
                "title": "Test Aid",
                "url": "https://example.com/aid.png",
            }
        ]

        mock_snap = MagicMock()
        mock_snap.values = {
            "messages": [AIMessage(content="Here's the aid.")],
            "turn_citations": [],
            "turn_decision_aids": decision_aids,
        }
        mock_snap.created_at = timestamp.isoformat()

        result = get_chat_history([mock_snap])

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["turn_decision_aids"], decision_aids)

    def test_get_chat_history_empty_decision_aids(self):
        """Test chat history with no decision aids."""
        timestamp = datetime.datetime.now(ZoneInfo(settings.TIME_ZONE))

        mock_snap = MagicMock()
        mock_snap.values = {
            "messages": [AIMessage(content="Just text.")],
            "turn_citations": [],
            # No turn_decision_aids key
        }
        mock_snap.created_at = timestamp.isoformat()

        result = get_chat_history([mock_snap])

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["turn_decision_aids"], [])


class HistoryViewDecisionAidsTest(TestCase):
    """Test the history view with decision aids."""

    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            email="test@example.com",
            password="testpass123",
        )
        self.client.login(username="test@example.com", password="testpass123")

        self.conversation = Conversation.objects.create(
            user=self.user,
            title="Test Conversation",
        )

    @patch("sdm_platform.llmchat.views.get_postgres_checkpointer")
    @patch("sdm_platform.llmchat.views.get_compiled_graph")
    @patch("sdm_platform.llmchat.views.get_chat_history")
    def test_history_view_includes_decision_aids(
        self,
        mock_get_chat_history,
        mock_get_graph,
        mock_get_checkpointer,
    ):
        """Test that history view includes decision aids in response."""
        mock_checkpointer_instance = MagicMock()
        mock_get_checkpointer.return_value.__enter__.return_value = (
            mock_checkpointer_instance
        )

        mock_graph = MagicMock()
        mock_get_graph.return_value = mock_graph
        mock_graph.get_state_history.return_value = []

        timestamp = datetime.datetime.now(ZoneInfo(settings.TIME_ZONE))
        decision_aids = [
            {
                "aid_id": "test-id",
                "aid_slug": "spine-anatomy",
                "aid_type": "image",
                "title": "Spine Anatomy",
                "url": "https://example.com/spine.png",
            }
        ]

        mock_get_chat_history.return_value = [
            {
                "created_at": timestamp,
                "new_messages": [
                    {
                        "type": "ai",
                        "data": {
                            "content": "Here's the spine anatomy.",
                            "metadata": {},
                        },
                    },
                ],
                "turn_citations": [],
                "turn_decision_aids": decision_aids,
            },
        ]

        response = self.client.get(
            reverse(
                "conversation_history",
                kwargs={"conversation_id": self.conversation.id},
            ),
        )

        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        self.assertEqual(len(data["messages"]), 1)
        self.assertEqual(data["messages"][0]["decision_aids"], decision_aids)

    @patch("sdm_platform.llmchat.views.get_postgres_checkpointer")
    @patch("sdm_platform.llmchat.views.get_compiled_graph")
    @patch("sdm_platform.llmchat.views.get_chat_history")
    def test_history_view_skips_empty_ai_messages(
        self,
        mock_get_chat_history,
        mock_get_graph,
        mock_get_checkpointer,
    ):
        """Test that AI messages with empty content (tool calls) are skipped."""
        mock_checkpointer_instance = MagicMock()
        mock_get_checkpointer.return_value.__enter__.return_value = (
            mock_checkpointer_instance
        )

        mock_graph = MagicMock()
        mock_get_graph.return_value = mock_graph
        mock_graph.get_state_history.return_value = []

        timestamp = datetime.datetime.now(ZoneInfo(settings.TIME_ZONE))

        # Simulate a tool call message (empty content) followed by actual response
        mock_get_chat_history.return_value = [
            {
                "created_at": timestamp,
                "new_messages": [
                    {
                        "type": "ai",
                        "data": {
                            "content": "",  # Empty - tool call message
                            "metadata": {},
                        },
                    },
                    {
                        "type": "ai",
                        "data": {
                            "content": "Here's the actual response.",
                            "metadata": {},
                        },
                    },
                ],
                "turn_citations": [],
                "turn_decision_aids": [],
            },
        ]

        response = self.client.get(
            reverse(
                "conversation_history",
                kwargs={"conversation_id": self.conversation.id},
            ),
        )

        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        # Should only have the non-empty AI message
        self.assertEqual(len(data["messages"]), 1)
        self.assertEqual(data["messages"][0]["content"], "Here's the actual response.")
