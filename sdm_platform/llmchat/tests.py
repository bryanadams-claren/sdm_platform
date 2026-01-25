# ruff: noqa: PT027, S106
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

from sdm_platform.llmchat.consumers import ChatConsumer
from sdm_platform.llmchat.consumers import get_useremail_from_scope
from sdm_platform.llmchat.models import Conversation
from sdm_platform.llmchat.tasks import send_llm_reply
from sdm_platform.llmchat.utils.chat_history import get_chat_history
from sdm_platform.llmchat.utils.format import format_message
from sdm_platform.llmchat.utils.format import format_thread_id
from sdm_platform.llmchat.utils.graphs import get_compiled_graph
from sdm_platform.llmchat.utils.graphs import get_postgres_checkpointer
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
            conv_id="test_conv",
            title="Test Conversation",
            thread_id="chat_test_example.com_test_conv",
        )

        self.assertIsNotNone(conv.id)
        self.assertEqual(conv.user, self.user)
        self.assertEqual(conv.conv_id, "test_conv")
        self.assertEqual(conv.title, "Test Conversation")
        self.assertTrue(conv.is_active)
        self.assertEqual(conv.model_name, "gpt-4")

    def test_conversation_str_representation(self):
        """Test the string representation of a conversation"""
        conv = Conversation.objects.create(
            user=self.user,
            conv_id="test_conv",
            title="Test Title",
            thread_id="chat_test_example.com_test_conv",
        )

        expected = f"Conversation: {self.user.email} / Test Title ({conv.id})"
        self.assertEqual(str(conv), expected)

    def test_conversation_defaults(self):
        """Test default values for conversation fields"""
        conv = Conversation.objects.create(
            user=self.user,
            conv_id="test_conv",
            thread_id="chat_test_example.com_test_conv",
        )

        self.assertEqual(conv.title, "")
        self.assertEqual(conv.system_prompt, "")
        self.assertEqual(conv.model_name, "gpt-4")
        self.assertTrue(conv.is_active)

    def test_conversation_updated_at_changes(self):
        """Test that updated_at changes when conversation is saved"""
        conv = Conversation.objects.create(
            user=self.user,
            conv_id="test_conv",
            thread_id="chat_test_example.com_test_conv",
        )

        original_updated_at = conv.updated_at
        conv.title = "Updated Title"
        conv.save()

        self.assertGreater(conv.updated_at, original_updated_at)

    def test_conversation_unique_thread_id(self):
        """Test that thread_id must be unique"""
        Conversation.objects.create(
            user=self.user,
            conv_id="conv1",
            thread_id="unique_thread_id",
        )

        # Creating another conversation with the same thread_id should fail
        with self.assertRaises(Exception):  # IntegrityError in production  # noqa: B017
            Conversation.objects.create(
                user=self.user,
                conv_id="conv2",
                thread_id="unique_thread_id",
            )

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
            conv_id="test_conv",
            thread_id="chat_test_example.com_test_conv",
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
        response = self.client.get(reverse("chat_conversation_top"))

        # Should redirect to login
        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response.url)  # pyright: ignore[reportAttributeAccessIssue]

    def test_conversation_view_creates_default_conversation(self):
        """Test that accessing conversation view creates a default conversation"""
        response = self.client.get(reverse("chat_conversation_top"))

        self.assertEqual(response.status_code, 200)
        conversations = Conversation.objects.filter(user=self.user)
        self.assertEqual(conversations.count(), 1)
        self.assertEqual(conversations[0].conv_id, settings.DEFAULT_CONV_ID)
        self.assertEqual(conversations[0].title, "General Q&A")

    def test_conversation_view_with_existing_conversations(self):
        """Test conversation view when conversations already exist"""
        conv1 = Conversation.objects.create(
            user=self.user,
            conv_id="conv1",
            title="First Conversation",
            thread_id="chat_test_example.com_conv1",
        )

        response = self.client.get(reverse("chat_conversation_top"))

        self.assertEqual(response.status_code, 200)
        self.assertIn("conversations", response.context)
        self.assertEqual(response.context["active_conv_id"], conv1.conv_id)

    def test_conversation_view_with_specific_conv_id(self):
        """Test conversation view with a specific conv_id"""
        conv1 = Conversation.objects.create(  # noqa: F841
            user=self.user,
            conv_id="conv1",
            title="First Conversation",
            thread_id="chat_test_example.com_conv1",
        )

        response = self.client.get(
            reverse("chat_conversation", kwargs={"conv_id": "conv1"}),
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["active_conv_id"], "conv1")

    def test_conversation_create_via_post(self):
        """Test creating a conversation via POST"""
        data = {
            "title": "New Conversation",
        }

        response = self.client.post(
            reverse("chat_conversation", kwargs={"conv_id": "new_conv"}),
            data=json.dumps(data),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        response_data = json.loads(response.content)
        self.assertTrue(response_data["success"])

        # Verify conversation was created
        conv = Conversation.objects.get(conv_id="new_conv")
        self.assertEqual(conv.title, "New Conversation")
        self.assertEqual(conv.user, self.user)

    def test_conversation_create_with_invalid_json(self):
        """Test creating a conversation with invalid JSON"""
        response = self.client.post(
            reverse("chat_conversation", kwargs={"conv_id": "new_conv"}),
            data="invalid json",
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        response_data = json.loads(response.content)
        self.assertFalse(response_data["success"])
        self.assertIn("error", response_data)


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
            conv_id="test_conv",
            title="Test Conversation",
            thread_id="chat_test_example.com_test_conv",
        )

    def test_history_view_requires_login(self):
        """Test that history view requires authentication"""
        self.client.logout()
        response = self.client.get(
            reverse("chat_history", kwargs={"conv_id": "test_conv"}),
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
            reverse("chat_history", kwargs={"conv_id": "test_conv"}),
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

    def test_format_thread_id(self):
        """Test formatting thread IDs"""
        result = format_thread_id("user@example.com", "conv123")
        self.assertEqual(result, "chat_user_at_example.com_conv123")

    def test_format_thread_id_with_spaces(self):
        """Test formatting thread IDs with spaces"""
        result = format_thread_id("user with spaces@example.com", "conv 123")
        self.assertEqual(result, "chat_user_with_spaces_at_example.com_conv_123")


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
            conv_id="test_conv",
            title="Test Conversation",
            thread_id="chat_test_example.com_test_conv",
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

        # Call the task
        send_llm_reply(
            thread_name="chat_test_example.com_test_conv",
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

        # Call the task
        send_llm_reply(
            thread_name="chat_test_example.com_test_conv",
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

        # Call the task
        send_llm_reply(
            thread_name="chat_test_example.com_test_conv",
            username="test@example.com",
            user_input="Hello",
        )

        # Verify async_to_sync was NOT called (no AI response)
        mock_async_to_sync.assert_not_called()


class URLConfigTest(TestCase):
    """Test URL configuration"""

    def test_url_patterns_exist(self):
        """Test that expected URL patterns are configured"""
        # Test conversation top level URL (with /chat/ prefix from main urls.py)
        url = reverse("chat_conversation_top")
        self.assertEqual(url, "/chat/conversation/")

        # Test conversation with conv_id
        url = reverse("chat_conversation", kwargs={"conv_id": "test123"})
        self.assertEqual(url, "/chat/conversation/test123/")

        # Test history URL
        url = reverse("chat_history", kwargs={"conv_id": "test123"})
        self.assertEqual(url, "/chat/history/test123/")


class ChatConsumerTest(TransactionTestCase):
    """Test the WebSocket ChatConsumer - uses TransactionTestCase for async support"""

    def setUp(self):
        self.user = User.objects.create_user(
            email="test@example.com",
            password="testpass123",
        )
        self.conversation = Conversation.objects.create(
            user=self.user,
            conv_id="test_conv",
            title="Test Conversation",
            thread_id="chat_test_example.com_test_conv",
        )

    @patch("sdm_platform.llmchat.consumers.send_llm_reply")
    async def test_consumer_connect(self, mock_send_llm_reply):
        """Test WebSocket connection"""

        # Get user in async-safe way
        @database_sync_to_async
        def get_user():
            return User.objects.get(email="test@example.com")

        user = await get_user()

        # Create communicator with user in scope
        communicator = WebsocketCommunicator(
            ChatConsumer.as_asgi(),
            "/ws/chat/test_conv/",
        )
        communicator.scope["user"] = user
        communicator.scope["url_route"] = {
            "kwargs": {"conv_id": "test_conv"},
        }

        # Connect
        connected, _ = await communicator.connect()
        self.assertTrue(connected)

        # Disconnect
        await communicator.disconnect()

    @patch("sdm_platform.llmchat.consumers.send_llm_reply")
    async def test_consumer_receive_message(self, mock_send_llm_reply):
        """Test receiving a message through WebSocket"""

        # Get user in async-safe way
        @database_sync_to_async
        def get_user():
            return User.objects.get(email="test@example.com")

        user = await get_user()

        # Create communicator
        communicator = WebsocketCommunicator(
            ChatConsumer.as_asgi(),
            "/ws/chat/test_conv/",
        )
        communicator.scope["user"] = user
        communicator.scope["url_route"] = {
            "kwargs": {"conv_id": "test_conv"},
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

        # Verify Celery task was called
        mock_send_llm_reply.delay.assert_called_once_with(
            "chat_test_at_example.com_test_conv",
            "test@example.com",
            "Hello, bot!",
        )

        # Disconnect
        await communicator.disconnect()

    @patch("sdm_platform.llmchat.consumers.send_llm_reply")
    async def test_consumer_ping_pong(self, mock_send_llm_reply):
        """Test ping/pong functionality"""

        # Get user in async-safe way
        @database_sync_to_async
        def get_user():
            return User.objects.get(email="test@example.com")

        user = await get_user()

        # Create communicator
        communicator = WebsocketCommunicator(
            ChatConsumer.as_asgi(),
            "/ws/chat/test_conv/",
        )
        communicator.scope["user"] = user
        communicator.scope["url_route"] = {
            "kwargs": {"conv_id": "test_conv"},
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
    async def test_consumer_without_conv_id(self, mock_send_llm_reply):
        """Test WebSocket connection without conv_id"""

        # Get user in async-safe way
        @database_sync_to_async
        def get_user():
            return User.objects.get(email="test@example.com")

        user = await get_user()

        # Create communicator without conv_id
        communicator = WebsocketCommunicator(
            ChatConsumer.as_asgi(),
            "/ws/chat/",
        )
        communicator.scope["user"] = user
        communicator.scope["url_route"] = {
            "kwargs": {},  # No conv_id
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
        self.assertIn("NoThreadIDAvailable", call_args[0])

        # Disconnect
        await communicator.disconnect()

    @patch("sdm_platform.llmchat.consumers.send_llm_reply")
    async def test_consumer_chat_reply(self, mock_send_llm_reply):
        """Test receiving a bot reply through the consumer"""

        # Get user in async-safe way
        @database_sync_to_async
        def get_user():
            return User.objects.get(email="test@example.com")

        user = await get_user()

        # Create communicator
        communicator = WebsocketCommunicator(
            ChatConsumer.as_asgi(),
            "/ws/chat/test_conv/",
        )
        communicator.scope["user"] = user
        communicator.scope["url_route"] = {
            "kwargs": {"conv_id": "test_conv"},
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
        channel_layer = get_channel_layer()
        if channel_layer:
            await channel_layer.group_send(
                "chat_test_at_example.com_test_conv",
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
