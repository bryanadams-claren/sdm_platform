# ruff: noqa: PT009, S106, PLC0415
# PT009 is assert stuff
# S106 is passwords
# PLC0415 is local imports
"""Tests for memory module."""

from datetime import UTC
from datetime import date
from datetime import datetime
from unittest.mock import MagicMock
from unittest.mock import patch

from django.test import TestCase

from sdm_platform.memory.managers import UserProfileManager
from sdm_platform.memory.schemas import UserProfileMemory
from sdm_platform.memory.store import get_user_namespace
from sdm_platform.users.models import User


class UserProfileMemorySchemaTest(TestCase):
    """Test the UserProfileMemory Pydantic schema."""

    def test_schema_creation_with_all_fields(self):
        """Test creating a profile with all fields."""
        profile = UserProfileMemory(
            name="Jane Doe",
            preferred_name="Jane",
            birthday=date(1985, 3, 15),
            source="user_input",
        )

        self.assertEqual(profile.name, "Jane Doe")
        self.assertEqual(profile.preferred_name, "Jane")
        self.assertEqual(profile.birthday, date(1985, 3, 15))
        self.assertEqual(profile.source, "user_input")
        self.assertIsInstance(profile.updated_at, datetime)
        self.assertIsNotNone(profile.updated_at.tzinfo)  # Timezone-aware

    def test_schema_creation_with_minimal_fields(self):
        """Test creating a profile with only required fields (none are required)."""
        profile = UserProfileMemory()

        self.assertIsNone(profile.name)
        self.assertIsNone(profile.preferred_name)
        self.assertIsNone(profile.birthday)
        self.assertEqual(profile.source, "llm_extraction")  # Default
        self.assertIsInstance(profile.updated_at, datetime)

    def test_schema_updated_at_default(self):
        """Test that updated_at defaults to current UTC time."""
        before = datetime.now(UTC)
        profile = UserProfileMemory()
        after = datetime.now(UTC)

        self.assertGreaterEqual(profile.updated_at, before)
        self.assertLessEqual(profile.updated_at, after)

    def test_schema_model_dump(self):
        """Test serialization to dict."""
        profile = UserProfileMemory(
            name="John Smith",
            birthday=date(1990, 6, 20),
        )

        data = profile.model_dump()

        self.assertIsInstance(data, dict)
        self.assertEqual(data["name"], "John Smith")
        self.assertEqual(data["birthday"], date(1990, 6, 20))
        self.assertIsNone(data["preferred_name"])


class UserNamespaceTest(TestCase):
    """Test namespace generation utilities."""

    def test_namespace_encoding_is_deterministic(self):
        """Test that the same email always produces the same encoded namespace."""
        namespace1 = get_user_namespace("test@example.com", "profile")
        namespace2 = get_user_namespace("test@example.com", "profile")

        self.assertEqual(namespace1, namespace2)

    def test_profile_namespace(self):
        """Test generating namespace for profile."""
        namespace = get_user_namespace("user@example.com", "profile")

        # Namespace should have encoded user_id (no periods)
        self.assertEqual(len(namespace), 4)
        self.assertEqual(namespace[0], "memory")
        self.assertEqual(namespace[1], "users")
        self.assertNotIn(".", namespace[2])  # No periods in encoded ID
        self.assertEqual(namespace[3], "profile")

    def test_journey_namespace(self):
        """Test generating namespace for journey memory."""
        namespace = get_user_namespace(
            "user@example.com",
            "journey",
            journey_slug="backpain",
        )

        # Namespace should have encoded user_id (no periods)
        self.assertEqual(len(namespace), 5)
        self.assertEqual(namespace[0], "memory")
        self.assertEqual(namespace[1], "users")
        self.assertNotIn(".", namespace[2])  # No periods in encoded ID
        self.assertEqual(namespace[3], "journeys")
        self.assertEqual(namespace[4], "backpain")

    def test_insights_namespace(self):
        """Test generating namespace for insights."""
        namespace = get_user_namespace("user@example.com", "insights")

        # Namespace should have encoded user_id (no periods)
        self.assertEqual(len(namespace), 4)
        self.assertEqual(namespace[0], "memory")
        self.assertEqual(namespace[1], "users")
        self.assertNotIn(".", namespace[2])  # No periods in encoded ID
        self.assertEqual(namespace[3], "insights")

    def test_unknown_memory_type_namespace(self):
        """Test generating namespace for unknown memory type."""
        namespace = get_user_namespace("user@example.com", "custom_type")

        # Namespace should have encoded user_id (no periods)
        self.assertEqual(len(namespace), 4)
        self.assertEqual(namespace[0], "memory")
        self.assertEqual(namespace[1], "users")
        self.assertNotIn(".", namespace[2])  # No periods in encoded ID
        self.assertEqual(namespace[3], "custom_type")


class UserProfileManagerTest(TestCase):
    """Test the UserProfileManager."""

    def setUp(self):
        """Set up test fixtures."""
        self.user = User.objects.create_user(
            email="test@example.com",
            password="testpass123",
        )
        self.user_id = self.user.email

    def _create_mock_store(self, existing_profile=None):
        """Create a mock store with optional existing profile."""
        mock_store = MagicMock()

        if existing_profile:
            mock_result = MagicMock()
            mock_result.value = existing_profile
            mock_store.get.return_value = mock_result
        else:
            mock_store.get.return_value = None

        return mock_store

    def test_get_profile_returns_none_when_not_exists(self):
        """Test getting profile when it doesn't exist."""
        mock_store = self._create_mock_store()

        profile = UserProfileManager.get_profile(self.user_id, store=mock_store)

        self.assertIsNone(profile)
        mock_store.get.assert_called_once()

    def test_get_profile_returns_profile_when_exists(self):
        """Test getting profile when it exists."""
        existing_data = {
            "name": "Jane Doe",
            "preferred_name": "Jane",
            "birthday": "1985-03-15",
            "updated_at": datetime.now(UTC).isoformat(),
            "source": "user_input",
        }
        mock_store = self._create_mock_store(existing_data)

        profile = UserProfileManager.get_profile(self.user_id, store=mock_store)

        self.assertIsNotNone(profile)
        self.assertIsInstance(profile, UserProfileMemory)
        self.assertEqual(profile.name, "Jane Doe")  # pyright: ignore[reportOptionalMemberAccess]
        self.assertEqual(profile.preferred_name, "Jane")  # pyright: ignore[reportOptionalMemberAccess]
        self.assertEqual(profile.birthday, date(1985, 3, 15))  # pyright: ignore[reportOptionalMemberAccess]

    def test_update_profile_creates_new_profile(self):
        """Test updating profile when it doesn't exist (creates new)."""
        mock_store = self._create_mock_store()

        updates = {
            "name": "John Smith",
            "birthday": date(1990, 6, 20),
        }

        profile = UserProfileManager.update_profile(
            self.user_id,
            updates,
            store=mock_store,
            source="user_input",
        )

        self.assertEqual(profile.name, "John Smith")
        self.assertEqual(profile.birthday, date(1990, 6, 20))
        self.assertIsNone(profile.preferred_name)
        self.assertEqual(profile.source, "user_input")

        # Verify store.put was called
        mock_store.put.assert_called_once()

    def test_update_profile_merges_with_existing(self):
        """Test updating profile merges with existing data."""
        existing_data = {
            "name": "Jane Doe",
            "preferred_name": None,
            "birthday": "1985-03-15",
            "updated_at": datetime.now(UTC).isoformat(),
            "source": "llm_extraction",
        }
        mock_store = self._create_mock_store(existing_data)

        updates = {
            "preferred_name": "Jane",
        }

        profile = UserProfileManager.update_profile(
            self.user_id,
            updates,
            store=mock_store,
        )

        # Original fields preserved
        self.assertEqual(profile.name, "Jane Doe")
        self.assertEqual(profile.birthday, date(1985, 3, 15))
        # New field added
        self.assertEqual(profile.preferred_name, "Jane")

        mock_store.put.assert_called_once()

    def test_update_profile_ignores_none_values(self):
        """Test that None values don't overwrite existing data."""
        existing_data = {
            "name": "Jane Doe",
            "preferred_name": "Jane",
            "birthday": "1985-03-15",
            "updated_at": datetime.now(UTC).isoformat(),
            "source": "llm_extraction",
        }
        mock_store = self._create_mock_store(existing_data)

        updates = {
            "name": "Jane Smith",  # Will update
            "preferred_name": None,  # Should NOT overwrite
        }

        profile = UserProfileManager.update_profile(
            self.user_id,
            updates,
            store=mock_store,
        )

        self.assertEqual(profile.name, "Jane Smith")  # Updated
        self.assertEqual(profile.preferred_name, "Jane")  # Preserved

    def test_update_profile_updates_timestamp(self):
        """Test that updating profile updates the timestamp."""
        existing_data = {
            "name": "Jane Doe",
            "birthday": "1985-03-15",
            "updated_at": "2020-01-01T00:00:00+00:00",
            "source": "llm_extraction",
        }
        mock_store = self._create_mock_store(existing_data)

        before = datetime.now(UTC)
        profile = UserProfileManager.update_profile(
            self.user_id,
            {"preferred_name": "Jane"},
            store=mock_store,
        )
        after = datetime.now(UTC)

        self.assertGreater(profile.updated_at, datetime(2020, 1, 1, tzinfo=UTC))
        self.assertGreaterEqual(profile.updated_at, before)
        self.assertLessEqual(profile.updated_at, after)

    def test_format_for_prompt_empty_profile(self):
        """Test formatting empty profile returns empty string."""
        result = UserProfileManager.format_for_prompt(None)
        self.assertEqual(result, "")

    def test_format_for_prompt_with_preferred_name(self):
        """Test formatting profile with preferred name."""
        profile = UserProfileMemory(
            name="Jane Doe",
            preferred_name="Jane",
        )

        result = UserProfileManager.format_for_prompt(profile)

        self.assertIn("USER CONTEXT:", result)
        self.assertIn("prefers to be called Jane", result)
        self.assertNotIn(
            "Jane Doe", result
        )  # Full name not shown if preferred_name exists

    def test_format_for_prompt_with_name_only(self):
        """Test formatting profile with only full name."""
        profile = UserProfileMemory(name="John Smith")

        result = UserProfileManager.format_for_prompt(profile)

        self.assertIn("USER CONTEXT:", result)
        self.assertIn("John Smith", result)

    def test_format_for_prompt_with_birthday(self):
        """Test formatting profile with birthday."""
        profile = UserProfileMemory(
            name="Jane Doe",
            birthday=date(1985, 3, 15),
        )

        result = UserProfileManager.format_for_prompt(profile)

        self.assertIn("USER CONTEXT:", result)
        self.assertIn("birthday is March 15", result)

    def test_format_for_prompt_all_fields(self):
        """Test formatting profile with all fields."""
        profile = UserProfileMemory(
            name="Jane Doe",
            preferred_name="Jane",
            birthday=date(1985, 3, 15),
        )

        result = UserProfileManager.format_for_prompt(profile)

        self.assertIn("USER CONTEXT:", result)
        self.assertIn("prefers to be called Jane", result)
        self.assertIn("birthday is March 15", result)

    def test_format_for_prompt_empty_fields_returns_empty(self):
        """Test formatting profile with no filled fields returns empty."""
        profile = UserProfileMemory()

        result = UserProfileManager.format_for_prompt(profile)

        self.assertEqual(result, "")


class MemoryExtractionTaskTest(TestCase):
    """Test the memory extraction Celery task."""

    def setUp(self):
        """Set up test fixtures."""
        self.user = User.objects.create_user(
            email="test@example.com",
            password="testpass123",
        )
        self.user_id = self.user.email

    @patch("sdm_platform.memory.tasks.UserProfileManager.update_profile")
    @patch("sdm_platform.memory.tasks.init_chat_model")
    def test_extraction_with_profile_data(self, mock_init_model, mock_update):
        """Test extraction successfully identifies profile data."""
        from sdm_platform.memory.tasks import extract_user_profile_memory

        # Mock LLM response
        mock_model = MagicMock()
        mock_response = MagicMock()
        mock_response.content = '{"name": "Jane Doe", "birthday": "1985-03-15"}'
        mock_model.invoke.return_value = mock_response
        mock_init_model.return_value = mock_model

        messages = [
            {"role": "user", "content": "Hi, my name is Jane Doe"},
            {"role": "assistant", "content": "Hello Jane! How can I help you?"},
            {"role": "user", "content": "I was born on March 15, 1985"},
        ]

        extract_user_profile_memory(self.user_id, messages)

        # Verify update_profile was called with extracted data
        mock_update.assert_called_once()
        call_args = mock_update.call_args
        self.assertEqual(call_args[1]["user_id"], self.user_id)
        self.assertEqual(call_args[1]["updates"]["name"], "Jane Doe")
        self.assertEqual(call_args[1]["updates"]["birthday"], "1985-03-15")
        self.assertEqual(call_args[1]["source"], "llm_extraction")

    @patch("sdm_platform.memory.tasks.UserProfileManager.update_profile")
    @patch("sdm_platform.memory.tasks.init_chat_model")
    def test_extraction_with_no_data(self, mock_init_model, mock_update):
        """Test extraction with no profile data doesn't update."""
        from sdm_platform.memory.tasks import extract_user_profile_memory

        # Mock LLM response with empty object
        mock_model = MagicMock()
        mock_response = MagicMock()
        mock_response.content = "{}"
        mock_model.invoke.return_value = mock_response
        mock_init_model.return_value = mock_model

        messages = [
            {"role": "user", "content": "What's the weather like?"},
            {"role": "assistant", "content": "I don't have weather information."},
        ]

        extract_user_profile_memory(self.user_id, messages)

        # Verify update_profile was NOT called
        mock_update.assert_not_called()

    @patch("sdm_platform.memory.tasks.UserProfileManager.update_profile")
    @patch("sdm_platform.memory.tasks.init_chat_model")
    def test_extraction_handles_markdown_code_blocks(
        self, mock_init_model, mock_update
    ):
        """Test extraction handles LLM wrapping JSON in markdown."""
        from sdm_platform.memory.tasks import extract_user_profile_memory

        # Mock LLM response with markdown wrapper
        mock_model = MagicMock()
        mock_response = MagicMock()
        mock_response.content = '```json\n{"name": "John Smith"}\n```'
        mock_model.invoke.return_value = mock_response
        mock_init_model.return_value = mock_model

        messages = [{"role": "user", "content": "I'm John Smith"}]

        extract_user_profile_memory(self.user_id, messages)

        # Verify update_profile was called
        mock_update.assert_called_once()
        call_args = mock_update.call_args
        self.assertEqual(call_args[1]["updates"]["name"], "John Smith")

    @patch("sdm_platform.memory.tasks.logger")
    @patch("sdm_platform.memory.tasks.init_chat_model")
    def test_extraction_handles_invalid_json(self, mock_init_model, mock_logger):
        """Test extraction handles invalid JSON gracefully."""
        from sdm_platform.memory.tasks import extract_user_profile_memory

        # Mock LLM response with invalid JSON
        mock_model = MagicMock()
        mock_response = MagicMock()
        mock_response.content = "This is not JSON"
        mock_model.invoke.return_value = mock_response
        mock_init_model.return_value = mock_model

        messages = [{"role": "user", "content": "Hello"}]

        # Should not raise exception
        extract_user_profile_memory(self.user_id, messages)

        # Should log warning
        mock_logger.warning.assert_called_once()

    def test_extraction_with_empty_messages(self):
        """Test extraction with empty messages list."""
        from sdm_platform.memory.tasks import extract_user_profile_memory

        # Should return early without error
        extract_user_profile_memory(self.user_id, [])
