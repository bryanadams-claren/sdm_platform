# ruff: noqa: S106, PLC0415, PLR2004, PT027
# PT009 is assert stuff
# S106 is passwords
# PLC0415 is local imports
# PLR2004 is literal values
# PTC027 is assertRaises
"""Tests for memory module."""

from datetime import UTC
from datetime import date
from datetime import datetime
from io import BytesIO
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
        self.assertEqual(call_args[1]["updates"]["birthday"], date(1985, 3, 15))
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


class ConversationPointMemorySchemaTest(TestCase):
    """Test ConversationPointMemory Pydantic schema."""

    def test_schema_creation_with_all_fields(self):
        """Test creating schema with all fields."""
        from sdm_platform.memory.schemas import ConversationPointMemory

        memory = ConversationPointMemory(
            conversation_point_slug="treatment-goals",
            journey_slug="backpain",
            is_addressed=True,
            confidence_score=0.85,
            extracted_points=["Wants to garden", "Walk without pain"],
            relevant_quotes=["I miss gardening"],
            structured_data={"activities": ["gardening"]},
            first_addressed_at=datetime.now(UTC),
            last_analyzed_at=datetime.now(UTC),
            message_count_analyzed=10,
        )

        assert memory.conversation_point_slug == "treatment-goals"
        assert memory.journey_slug == "backpain"
        assert memory.is_addressed is True
        assert memory.confidence_score == 0.85
        assert len(memory.extracted_points) == 2
        assert len(memory.relevant_quotes) == 1
        assert memory.structured_data == {"activities": ["gardening"]}
        assert memory.message_count_analyzed == 10
        assert memory.first_addressed_at is not None
        assert memory.last_analyzed_at is not None

    def test_schema_creation_with_minimal_fields(self):
        """Test creating schema with only required fields."""
        from sdm_platform.memory.schemas import ConversationPointMemory

        memory = ConversationPointMemory(
            conversation_point_slug="treatment-goals",
            journey_slug="backpain",
        )

        assert memory.conversation_point_slug == "treatment-goals"
        assert memory.journey_slug == "backpain"
        assert memory.is_addressed is False
        assert memory.confidence_score == 0.0
        assert memory.extracted_points == []
        assert memory.relevant_quotes == []
        assert memory.structured_data == {}
        assert memory.message_count_analyzed == 0
        assert memory.first_addressed_at is None
        # last_analyzed_at should have a default
        assert isinstance(memory.last_analyzed_at, datetime)

    def test_schema_confidence_score_validation(self):
        """Test confidence score must be between 0 and 1."""
        from pydantic import ValidationError

        from sdm_platform.memory.schemas import ConversationPointMemory

        # Valid scores
        memory1 = ConversationPointMemory(
            conversation_point_slug="test",
            journey_slug="backpain",
            confidence_score=0.0,
        )
        assert memory1.confidence_score == 0.0

        memory2 = ConversationPointMemory(
            conversation_point_slug="test",
            journey_slug="backpain",
            confidence_score=1.0,
        )
        assert memory2.confidence_score == 1.0

        # Invalid scores should raise ValidationError
        with self.assertRaises(ValidationError):
            ConversationPointMemory(
                conversation_point_slug="test",
                journey_slug="backpain",
                confidence_score=-0.1,
            )

        with self.assertRaises(ValidationError):
            ConversationPointMemory(
                conversation_point_slug="test",
                journey_slug="backpain",
                confidence_score=1.1,
            )

    def test_schema_last_analyzed_at_default(self):
        """Test that last_analyzed_at has a default value."""
        from sdm_platform.memory.schemas import ConversationPointMemory

        memory = ConversationPointMemory(
            conversation_point_slug="test",
            journey_slug="backpain",
        )

        # Should have a default timestamp
        assert isinstance(memory.last_analyzed_at, datetime)
        assert memory.last_analyzed_at.tzinfo is not None  # Should be timezone-aware

    def test_schema_first_addressed_at_defaults_to_none(self):
        """Test that first_addressed_at defaults to None."""
        from sdm_platform.memory.schemas import ConversationPointMemory

        memory = ConversationPointMemory(
            conversation_point_slug="test",
            journey_slug="backpain",
        )

        # Should be None by default
        assert memory.first_addressed_at is None

    def test_schema_message_count_defaults_to_zero(self):
        """Test that message_count_analyzed defaults to 0."""
        from sdm_platform.memory.schemas import ConversationPointMemory

        memory = ConversationPointMemory(
            conversation_point_slug="test",
            journey_slug="backpain",
        )

        assert memory.message_count_analyzed == 0

    def test_schema_model_dump(self):
        """Test model serialization."""
        from sdm_platform.memory.schemas import ConversationPointMemory

        memory = ConversationPointMemory(
            conversation_point_slug="treatment-goals",
            journey_slug="backpain",
            is_addressed=True,
            confidence_score=0.75,
            extracted_points=["Point 1", "Point 2"],
            relevant_quotes=["Quote 1"],
            structured_data={"key": "value"},
            message_count_analyzed=5,
        )

        dumped = memory.model_dump(mode="json")

        assert isinstance(dumped, dict)
        assert dumped["conversation_point_slug"] == "treatment-goals"
        assert dumped["journey_slug"] == "backpain"
        assert dumped["is_addressed"] is True
        assert dumped["confidence_score"] == 0.75
        assert len(dumped["extracted_points"]) == 2
        assert len(dumped["relevant_quotes"]) == 1
        assert dumped["structured_data"] == {"key": "value"}
        assert dumped["message_count_analyzed"] == 5


class ConversationPointNamespaceTest(TestCase):
    """Test namespace generation for conversation points."""

    def test_conversation_points_namespace(self):
        """Test conversation points namespace includes journey slug."""
        namespace = get_user_namespace(
            "user@example.com",
            "conversation_points",
            journey_slug="backpain",
        )

        assert isinstance(namespace, tuple)
        assert namespace[0] == "memory"
        assert namespace[1] == "users"
        assert namespace[3] == "conversation_points"
        assert namespace[4] == "backpain"

    def test_conversation_points_namespace_different_journeys(self):
        """Test that different journeys get different namespaces."""
        namespace1 = get_user_namespace(
            "user@example.com",
            "conversation_points",
            journey_slug="backpain",
        )
        namespace2 = get_user_namespace(
            "user@example.com",
            "conversation_points",
            journey_slug="kneepain",
        )

        # Same user, different journeys should have different namespaces
        assert namespace1[4] == "backpain"
        assert namespace2[4] == "kneepain"
        assert namespace1 != namespace2

    def test_conversation_points_namespace_different_users(self):
        """Test that different users get different namespaces."""
        namespace1 = get_user_namespace(
            "user1@example.com",
            "conversation_points",
            journey_slug="backpain",
        )
        namespace2 = get_user_namespace(
            "user2@example.com",
            "conversation_points",
            journey_slug="backpain",
        )

        # Different users should have different encoded IDs
        assert namespace1[2] != namespace2[2]
        # But same journey slug
        assert namespace1[4] == namespace2[4]


class ConversationPointManagerTest(TestCase):
    """Test ConversationPointManager."""

    def setUp(self):
        self.user_id = "test@example.com"
        self.journey_slug = "backpain"
        self.point_slug = "treatment-goals"

    def _create_mock_store(self, return_value=None):
        """Create a mock store for testing."""
        mock_store = MagicMock()
        mock_store.get.return_value = return_value
        mock_store.put.return_value = None
        mock_store.search.return_value = []
        mock_store.__enter__ = MagicMock(return_value=mock_store)
        mock_store.__exit__ = MagicMock(return_value=False)
        return mock_store

    def test_get_point_memory_returns_none_when_not_exists(self):
        """Test getting a non-existent conversation point memory."""
        from sdm_platform.memory.managers import ConversationPointManager

        mock_store = self._create_mock_store(return_value=None)

        memory = ConversationPointManager.get_point_memory(
            user_id=self.user_id,
            journey_slug=self.journey_slug,
            point_slug=self.point_slug,
            store=mock_store,
        )

        assert memory is None
        mock_store.get.assert_called_once()

    def test_get_point_memory_returns_memory_when_exists(self):
        """Test getting an existing conversation point memory."""
        from sdm_platform.memory.managers import ConversationPointManager

        # Mock existing memory
        mock_item = MagicMock()
        mock_item.value = {
            "conversation_point_slug": self.point_slug,
            "journey_slug": self.journey_slug,
            "is_addressed": True,
            "confidence_score": 0.85,
            "extracted_points": ["Point 1"],
            "relevant_quotes": ["Quote 1"],
            "structured_data": {"key": "value"},
            "first_addressed_at": datetime.now(UTC).isoformat(),
            "last_analyzed_at": datetime.now(UTC).isoformat(),
            "message_count_analyzed": 5,
        }
        mock_store = self._create_mock_store(return_value=mock_item)

        memory = ConversationPointManager.get_point_memory(
            user_id=self.user_id,
            journey_slug=self.journey_slug,
            point_slug=self.point_slug,
            store=mock_store,
        )

        assert memory is not None
        assert memory.conversation_point_slug == self.point_slug
        assert memory.is_addressed is True
        assert memory.confidence_score == 0.85
        assert len(memory.extracted_points) == 1
        assert memory.message_count_analyzed == 5

    def test_update_point_memory_creates_new(self):
        """Test updating conversation point memory creates new if not exists."""
        from sdm_platform.memory.managers import ConversationPointManager

        mock_store = self._create_mock_store(return_value=None)

        updates = {
            "is_addressed": True,
            "confidence_score": 0.75,
            "extracted_points": ["User wants to garden"],
            "message_count_analyzed": 3,
        }

        memory = ConversationPointManager.update_point_memory(
            user_id=self.user_id,
            journey_slug=self.journey_slug,
            point_slug=self.point_slug,
            updates=updates,
            store=mock_store,
        )

        assert memory.conversation_point_slug == self.point_slug
        assert memory.journey_slug == self.journey_slug
        assert memory.is_addressed is True
        assert memory.confidence_score == 0.75
        assert "User wants to garden" in memory.extracted_points
        assert memory.message_count_analyzed == 3
        mock_store.put.assert_called_once()

    def test_update_point_memory_merges_with_existing(self):
        """Test updating merges with existing memory."""
        from sdm_platform.memory.managers import ConversationPointManager

        # Mock existing memory
        mock_item = MagicMock()
        mock_item.value = {
            "conversation_point_slug": self.point_slug,
            "journey_slug": self.journey_slug,
            "is_addressed": False,
            "confidence_score": 0.3,
            "extracted_points": ["Old point"],
            "relevant_quotes": [],
            "structured_data": {},
            "first_addressed_at": None,
            "last_analyzed_at": datetime.now(UTC).isoformat(),
            "message_count_analyzed": 2,
        }
        mock_store = self._create_mock_store(return_value=mock_item)

        updates = {
            "is_addressed": True,
            "confidence_score": 0.85,
            "extracted_points": ["New point"],
            "message_count_analyzed": 5,
        }

        memory = ConversationPointManager.update_point_memory(
            user_id=self.user_id,
            journey_slug=self.journey_slug,
            point_slug=self.point_slug,
            updates=updates,
            store=mock_store,
        )

        # Should have updated values
        assert memory.is_addressed is True
        assert memory.confidence_score == 0.85
        assert memory.extracted_points == ["New point"]
        assert memory.message_count_analyzed == 5

    def test_update_point_memory_ignores_none_values(self):
        """Test that None values in updates are ignored."""
        from sdm_platform.memory.managers import ConversationPointManager

        # Mock existing memory
        mock_item = MagicMock()
        mock_item.value = {
            "conversation_point_slug": self.point_slug,
            "journey_slug": self.journey_slug,
            "is_addressed": True,
            "confidence_score": 0.85,
            "extracted_points": ["Keep this"],
            "relevant_quotes": [],
            "structured_data": {},
            "first_addressed_at": datetime.now(UTC).isoformat(),
            "last_analyzed_at": datetime.now(UTC).isoformat(),
            "message_count_analyzed": 5,
        }
        mock_store = self._create_mock_store(return_value=mock_item)

        updates = {
            "confidence_score": None,  # Should be ignored
            "message_count_analyzed": 10,  # Should be updated
        }

        memory = ConversationPointManager.update_point_memory(
            user_id=self.user_id,
            journey_slug=self.journey_slug,
            point_slug=self.point_slug,
            updates=updates,
            store=mock_store,
        )

        # confidence_score should remain unchanged
        assert memory.confidence_score == 0.85
        # message_count_analyzed should be updated
        assert memory.message_count_analyzed == 10

    def test_update_point_memory_updates_last_analyzed_at(self):
        """Test that update always updates last_analyzed_at timestamp."""
        from sdm_platform.memory.managers import ConversationPointManager

        mock_store = self._create_mock_store(return_value=None)

        before_update = datetime.now(UTC)

        memory = ConversationPointManager.update_point_memory(
            user_id=self.user_id,
            journey_slug=self.journey_slug,
            point_slug=self.point_slug,
            updates={"message_count_analyzed": 1},
            store=mock_store,
        )

        # last_analyzed_at should be recent
        assert memory.last_analyzed_at >= before_update

    def test_get_all_point_memories(self):
        """Test getting all conversation point memories for a journey."""
        from sdm_platform.memory.managers import ConversationPointManager

        # Mock search results
        mock_item1 = MagicMock()
        mock_item1.key = "point_treatment-goals"
        mock_item1.value = {
            "conversation_point_slug": "treatment-goals",
            "journey_slug": self.journey_slug,
            "is_addressed": True,
            "confidence_score": 0.85,
            "extracted_points": ["Goal 1"],
            "relevant_quotes": [],
            "structured_data": {},
            "first_addressed_at": datetime.now(UTC).isoformat(),
            "last_analyzed_at": datetime.now(UTC).isoformat(),
            "message_count_analyzed": 5,
        }

        mock_item2 = MagicMock()
        mock_item2.key = "point_preferences"
        mock_item2.value = {
            "conversation_point_slug": "preferences",
            "journey_slug": self.journey_slug,
            "is_addressed": False,
            "confidence_score": 0.2,
            "extracted_points": [],
            "relevant_quotes": [],
            "structured_data": {},
            "first_addressed_at": None,
            "last_analyzed_at": datetime.now(UTC).isoformat(),
            "message_count_analyzed": 3,
        }

        mock_store = self._create_mock_store()
        mock_store.search.return_value = [mock_item1, mock_item2]

        memories = ConversationPointManager.get_all_point_memories(
            user_id=self.user_id,
            journey_slug=self.journey_slug,
            store=mock_store,
        )

        assert len(memories) == 2
        assert memories[0].conversation_point_slug == "treatment-goals"
        assert memories[0].is_addressed is True
        assert memories[1].conversation_point_slug == "preferences"
        assert memories[1].is_addressed is False

    def test_get_all_point_memories_filters_non_point_items(self):
        """Test that get_all only returns items with point_ prefix."""
        from sdm_platform.memory.managers import ConversationPointManager

        # Mock search results with mixed keys
        mock_item1 = MagicMock()
        mock_item1.key = "point_treatment-goals"
        mock_item1.value = {
            "conversation_point_slug": "treatment-goals",
            "journey_slug": self.journey_slug,
            "is_addressed": True,
            "confidence_score": 0.85,
            "extracted_points": [],
            "relevant_quotes": [],
            "structured_data": {},
            "first_addressed_at": datetime.now(UTC).isoformat(),
            "last_analyzed_at": datetime.now(UTC).isoformat(),
            "message_count_analyzed": 5,
        }

        mock_item2 = MagicMock()
        mock_item2.key = "some_other_key"
        mock_item2.value = {"random": "data"}

        mock_store = self._create_mock_store()
        mock_store.search.return_value = [mock_item1, mock_item2]

        memories = ConversationPointManager.get_all_point_memories(
            user_id=self.user_id,
            journey_slug=self.journey_slug,
            store=mock_store,
        )

        # Should only return the point_ item
        assert len(memories) == 1
        assert memories[0].conversation_point_slug == "treatment-goals"


class ConversationPointExtractionTaskTest(TestCase):
    """Test conversation point memory extraction task."""

    def setUp(self):
        self.user_id = "test@example.com"
        self.journey_slug = "backpain"

        # Create test user
        User.objects.create_user(
            email=self.user_id,
            password="testpass123",
        )

    def _create_mock_conversation_point(
        self, slug, title, keywords, *, clear_existing=True
    ):
        """Helper to create a mock ConversationPoint."""
        from sdm_platform.journeys.models import Journey
        from sdm_platform.memory.models import ConversationPoint

        # Get or create journey
        journey, _ = Journey.objects.get_or_create(
            slug=self.journey_slug,
            defaults={
                "title": "Back Pain Decision Support",
                "description": "Test journey",
            },
        )

        # Clear existing conversation points for this journey if requested
        # (prevents interference from fixture data)
        if clear_existing:
            ConversationPoint.objects.filter(journey=journey).delete()

        # Create conversation point
        point, _ = ConversationPoint.objects.get_or_create(
            journey=journey,
            slug=slug,
            defaults={
                "title": title,
                "description": f"Test point: {title}",
                "system_message_template": f"Let's discuss {title}",
                "semantic_keywords": keywords,
            },
        )
        return point

    @patch("sdm_platform.memory.tasks.init_chat_model")
    def test_extraction_identifies_discussed_topic(self, mock_init_model):
        """Test extraction correctly identifies when a topic is discussed."""
        from sdm_platform.memory.tasks import extract_conversation_point_memories

        # Create conversation point
        self._create_mock_conversation_point(
            slug="treatment-goals",
            title="Discuss treatment goals",
            keywords=["goals", "hope to achieve", "activities"],
        )

        # Mock LLM response
        mock_model = MagicMock()
        mock_response = MagicMock()
        mock_response.content = """{
            "is_addressed": true,
            "confidence_score": 0.85,
            "extracted_points": ["Wants to return to gardening", "Walk without pain"],
            "relevant_quotes": ["I really miss being able to garden"],
            "structured_data": {"activities": ["gardening", "walking"]},
            "reasoning": "User clearly stated their goals"
        }"""
        mock_model.invoke.return_value = mock_response
        mock_init_model.return_value = mock_model

        messages = [
            {"role": "user", "content": "I really miss being able to garden"},
            {
                "role": "assistant",
                "content": "What activities are most important to you?",
            },
            {
                "role": "user",
                "content": "I'd love to walk around the block without pain",
            },
        ]

        # Mock the store
        with patch("sdm_platform.memory.managers.get_memory_store") as mock_store_ctx:
            mock_store = MagicMock()
            mock_store.get.return_value = None
            mock_store.put.return_value = None
            mock_store.__enter__ = MagicMock(return_value=mock_store)
            mock_store.__exit__ = MagicMock(return_value=False)
            mock_store_ctx.return_value = mock_store

            extract_conversation_point_memories(
                user_id=self.user_id,
                journey_slug=self.journey_slug,
                messages_json=messages,
            )

            # Verify LLM was called
            mock_model.invoke.assert_called_once()

            # Verify store.put was called to save the memory
            mock_store.put.assert_called_once()

            # Check the saved data
            call_args = mock_store.put.call_args
            saved_data = call_args[0][2]  # Third argument is the value
            assert saved_data["is_addressed"] is True
            assert saved_data["confidence_score"] == 0.85
            assert len(saved_data["extracted_points"]) == 2
            assert saved_data["message_count_analyzed"] == 3

    @patch("sdm_platform.memory.tasks.init_chat_model")
    def test_extraction_identifies_not_discussed_topic(self, mock_init_model):
        """Test extraction correctly identifies when a topic is not discussed."""
        from sdm_platform.memory.tasks import extract_conversation_point_memories

        # Create conversation point
        self._create_mock_conversation_point(
            slug="treatment-options",
            title="Understand treatment options",
            keywords=["treatment", "options", "surgery", "therapy"],
        )

        # Mock LLM response indicating topic not discussed
        mock_model = MagicMock()
        mock_response = MagicMock()
        mock_response.content = """{
            "is_addressed": false,
            "confidence_score": 0.0,
            "extracted_points": [],
            "relevant_quotes": [],
            "structured_data": {},
            "reasoning": "Conversation did not cover treatment options"
        }"""
        mock_model.invoke.return_value = mock_response
        mock_init_model.return_value = mock_model

        messages = [
            {"role": "user", "content": "My back has been hurting"},
            {"role": "assistant", "content": "How long has it been hurting?"},
            {"role": "user", "content": "About 3 months"},
        ]

        # Mock the store
        with patch("sdm_platform.memory.managers.get_memory_store") as mock_store_ctx:
            mock_store = MagicMock()
            mock_store.get.return_value = None
            mock_store.put.return_value = None
            mock_store.__enter__ = MagicMock(return_value=mock_store)
            mock_store.__exit__ = MagicMock(return_value=False)
            mock_store_ctx.return_value = mock_store

            extract_conversation_point_memories(
                user_id=self.user_id,
                journey_slug=self.journey_slug,
                messages_json=messages,
            )

            # Verify store.put was called
            mock_store.put.assert_called_once()

            # Check the saved data
            call_args = mock_store.put.call_args
            saved_data = call_args[0][2]
            assert saved_data["is_addressed"] is False
            assert saved_data["confidence_score"] == 0.0
            assert len(saved_data["extracted_points"]) == 0

    @patch("sdm_platform.memory.tasks.init_chat_model")
    def test_extraction_skips_already_addressed_high_confidence(self, mock_init_model):
        """Test that extraction skips topics already addressed with high confidence."""
        from sdm_platform.memory.tasks import extract_conversation_point_memories

        # Create conversation point
        self._create_mock_conversation_point(
            slug="treatment-goals",
            title="Discuss treatment goals",
            keywords=["goals"],
        )

        # Mock existing high-confidence memory
        mock_existing_item = MagicMock()
        mock_existing_item.value = {
            "conversation_point_slug": "treatment-goals",
            "journey_slug": self.journey_slug,
            "is_addressed": True,
            "confidence_score": 0.95,  # High confidence
            "extracted_points": ["Already captured"],
            "relevant_quotes": [],
            "structured_data": {},
            "first_addressed_at": datetime.now(UTC).isoformat(),
            "last_analyzed_at": datetime.now(UTC).isoformat(),
            "message_count_analyzed": 10,
        }

        mock_model = MagicMock()
        mock_init_model.return_value = mock_model

        messages = [
            {"role": "user", "content": "More discussion about goals"},
        ]

        # Mock the store
        with patch("sdm_platform.memory.managers.get_memory_store") as mock_store_ctx:
            mock_store = MagicMock()
            mock_store.get.return_value = mock_existing_item
            mock_store.put.return_value = None
            mock_store.__enter__ = MagicMock(return_value=mock_store)
            mock_store.__exit__ = MagicMock(return_value=False)
            mock_store_ctx.return_value = mock_store

            extract_conversation_point_memories(
                user_id=self.user_id,
                journey_slug=self.journey_slug,
                messages_json=messages,
            )

            # LLM should NOT be called since we're skipping
            mock_model.invoke.assert_not_called()

            # Store.put should NOT be called
            mock_store.put.assert_not_called()

    @patch("sdm_platform.memory.tasks.init_chat_model")
    def test_extraction_handles_markdown_code_blocks(self, mock_init_model):
        """Test extraction handles LLM responses wrapped in markdown code blocks."""
        from sdm_platform.memory.tasks import extract_conversation_point_memories

        # Create conversation point
        self._create_mock_conversation_point(
            slug="preferences",
            title="Analyze preferences",
            keywords=["prefer", "values"],
        )

        # Mock LLM response with markdown wrapper
        mock_model = MagicMock()
        mock_response = MagicMock()
        mock_response.content = """```json
{
    "is_addressed": true,
    "confidence_score": 0.7,
    "extracted_points": ["Prefers non-invasive"],
    "relevant_quotes": ["I prefer non-invasive treatments"],
    "structured_data": {"preference_type": "non-invasive"},
    "reasoning": "Stated preference"
}
```"""
        mock_model.invoke.return_value = mock_response
        mock_init_model.return_value = mock_model

        messages = [
            {"role": "user", "content": "I prefer non-invasive treatments"},
        ]

        # Mock the store
        with patch("sdm_platform.memory.managers.get_memory_store") as mock_store_ctx:
            mock_store = MagicMock()
            mock_store.get.return_value = None
            mock_store.put.return_value = None
            mock_store.__enter__ = MagicMock(return_value=mock_store)
            mock_store.__exit__ = MagicMock(return_value=False)
            mock_store_ctx.return_value = mock_store

            extract_conversation_point_memories(
                user_id=self.user_id,
                journey_slug=self.journey_slug,
                messages_json=messages,
            )

            # Verify it was parsed correctly despite markdown wrapper
            mock_store.put.assert_called_once()
            call_args = mock_store.put.call_args
            saved_data = call_args[0][2]
            assert saved_data["is_addressed"] is True
            assert saved_data["confidence_score"] == 0.7
            assert "Prefers non-invasive" in saved_data["extracted_points"]

    @patch("sdm_platform.memory.tasks.init_chat_model")
    def test_extraction_handles_invalid_json(self, mock_init_model):
        """Test extraction handles invalid JSON responses gracefully."""
        from sdm_platform.memory.tasks import extract_conversation_point_memories

        # Create conversation point
        self._create_mock_conversation_point(
            slug="demographics",
            title="Understand demographics",
            keywords=["age", "occupation"],
        )

        # Mock LLM response with invalid JSON
        mock_model = MagicMock()
        mock_response = MagicMock()
        mock_response.content = "This is not valid JSON {broken"
        mock_model.invoke.return_value = mock_response
        mock_init_model.return_value = mock_model

        messages = [
            {"role": "user", "content": "I'm 45 years old"},
        ]

        # Mock the store
        with patch("sdm_platform.memory.managers.get_memory_store") as mock_store_ctx:
            mock_store = MagicMock()
            mock_store.get.return_value = None
            mock_store.put.return_value = None
            mock_store.__enter__ = MagicMock(return_value=mock_store)
            mock_store.__exit__ = MagicMock(return_value=False)
            mock_store_ctx.return_value = mock_store

            # Should not raise exception
            extract_conversation_point_memories(
                user_id=self.user_id,
                journey_slug=self.journey_slug,
                messages_json=messages,
            )

            # Store.put should NOT be called due to JSON error
            mock_store.put.assert_not_called()

    def test_extraction_with_empty_messages(self):
        """Test extraction with empty messages list."""
        from sdm_platform.memory.tasks import extract_conversation_point_memories

        # Should return early without error
        extract_conversation_point_memories(
            user_id=self.user_id,
            journey_slug=self.journey_slug,
            messages_json=[],
        )

    def test_extraction_with_no_conversation_points(self):
        """Test extraction when journey has no conversation points."""
        from sdm_platform.memory.tasks import extract_conversation_point_memories

        messages = [
            {"role": "user", "content": "Hello"},
        ]

        # Should return early without error when no points exist
        extract_conversation_point_memories(
            user_id=self.user_id,
            journey_slug=self.journey_slug,
            messages_json=messages,
        )

    @patch("sdm_platform.memory.tasks.init_chat_model")
    def test_extraction_sets_first_addressed_at(self, mock_init_model):
        """Test that first_addressed_at is set when topic is first addressed."""
        from sdm_platform.memory.tasks import extract_conversation_point_memories

        # Create conversation point
        self._create_mock_conversation_point(
            slug="treatment-goals",
            title="Discuss treatment goals",
            keywords=["goals"],
        )

        # Mock LLM response indicating topic is addressed
        mock_model = MagicMock()
        mock_response = MagicMock()
        mock_response.content = """{
            "is_addressed": true,
            "confidence_score": 0.75,
            "extracted_points": ["First mention of goals"],
            "relevant_quotes": [],
            "structured_data": {},
            "reasoning": "User mentioned goals"
        }"""
        mock_model.invoke.return_value = mock_response
        mock_init_model.return_value = mock_model

        messages = [
            {"role": "user", "content": "My goal is to feel better"},
        ]

        # Mock the store (no existing memory)
        with patch("sdm_platform.memory.managers.get_memory_store") as mock_store_ctx:
            mock_store = MagicMock()
            mock_store.get.return_value = None  # No existing memory
            mock_store.put.return_value = None
            mock_store.__enter__ = MagicMock(return_value=mock_store)
            mock_store.__exit__ = MagicMock(return_value=False)
            mock_store_ctx.return_value = mock_store

            extract_conversation_point_memories(
                user_id=self.user_id,
                journey_slug=self.journey_slug,
                messages_json=messages,
            )

            # Verify first_addressed_at was set in the update
            mock_store.put.assert_called_once()
            call_args = mock_store.put.call_args
            saved_data = call_args[0][2]
            assert saved_data["is_addressed"] is True
            assert saved_data["first_addressed_at"] is not None

    @patch("sdm_platform.memory.tasks.extract_user_profile_memory")
    @patch("sdm_platform.memory.tasks.extract_conversation_point_memories")
    def test_extract_all_memories_calls_both_extractors(
        self, mock_cp_extract, mock_profile_extract
    ):
        """Test that extract_all_memories calls both extraction functions."""
        from sdm_platform.memory.tasks import extract_all_memories

        messages = [
            {"role": "user", "content": "Test message"},
        ]

        extract_all_memories(
            user_id=self.user_id,
            journey_slug=self.journey_slug,
            messages_json=messages,
        )

        # Both extractors should be called
        mock_profile_extract.assert_called_once_with(self.user_id, messages)
        mock_cp_extract.assert_called_once_with(
            self.user_id, self.journey_slug, messages
        )

    @patch("sdm_platform.memory.tasks.extract_user_profile_memory")
    @patch("sdm_platform.memory.tasks.extract_conversation_point_memories")
    def test_extract_all_memories_profile_only_when_no_journey(
        self, mock_cp_extract, mock_profile_extract
    ):
        """Test that only profile is extracted when no journey specified."""
        from sdm_platform.memory.tasks import extract_all_memories

        messages = [
            {"role": "user", "content": "Test message"},
        ]

        extract_all_memories(
            user_id=self.user_id,
            journey_slug=None,  # No journey
            messages_json=messages,
        )

        # Only profile extractor should be called
        mock_profile_extract.assert_called_once_with(self.user_id, messages)
        # Conversation points should NOT be called
        mock_cp_extract.assert_not_called()

    @patch("sdm_platform.memory.tasks.init_chat_model")
    def test_extraction_updates_message_count(self, mock_init_model):
        """Test that message_count_analyzed is properly updated."""
        from sdm_platform.memory.tasks import extract_conversation_point_memories

        # Create conversation point
        self._create_mock_conversation_point(
            slug="treatment-goals",
            title="Discuss treatment goals",
            keywords=["goals"],
        )

        # Mock LLM response
        mock_model = MagicMock()
        mock_response = MagicMock()
        mock_response.content = """{
            "is_addressed": false,
            "confidence_score": 0.1,
            "extracted_points": [],
            "relevant_quotes": [],
            "structured_data": {},
            "reasoning": "Minimal discussion"
        }"""
        mock_model.invoke.return_value = mock_response
        mock_init_model.return_value = mock_model

        messages = [
            {"role": "user", "content": "Message 1"},
            {"role": "assistant", "content": "Response 1"},
            {"role": "user", "content": "Message 2"},
            {"role": "assistant", "content": "Response 2"},
            {"role": "user", "content": "Message 3"},
        ]

        # Mock the store
        with patch("sdm_platform.memory.managers.get_memory_store") as mock_store_ctx:
            mock_store = MagicMock()
            mock_store.get.return_value = None
            mock_store.put.return_value = None
            mock_store.__enter__ = MagicMock(return_value=mock_store)
            mock_store.__exit__ = MagicMock(return_value=False)
            mock_store_ctx.return_value = mock_store

            extract_conversation_point_memories(
                user_id=self.user_id,
                journey_slug=self.journey_slug,
                messages_json=messages,
            )

            # Verify message_count_analyzed equals number of messages
            mock_store.put.assert_called_once()
            call_args = mock_store.put.call_args
            saved_data = call_args[0][2]
            assert saved_data["message_count_analyzed"] == 5


# ====== CONVERSATION SUMMARY PDF TESTS ======


class ConversationSummarySchemaTest(TestCase):
    """Test ConversationSummary Pydantic schemas."""

    def test_point_summary_schema(self):
        """Test PointSummary schema creation."""
        from sdm_platform.memory.schemas import PointSummary

        point = PointSummary(
            title="Treatment Goals",
            description="Discuss patient's treatment goals",
            extracted_points=["Return to gardening", "Walk without pain"],
            relevant_quotes=["I miss gardening"],
            structured_data={"activities": ["gardening", "walking"]},
            first_addressed_at=datetime.now(UTC),
        )

        assert point.title == "Treatment Goals"
        assert len(point.extracted_points) == 2
        assert len(point.relevant_quotes) == 1
        assert "activities" in point.structured_data

    def test_journey_option_summary_schema(self):
        """Test JourneyOptionSummary schema creation."""
        from sdm_platform.memory.schemas import JourneyOptionSummary

        option = JourneyOptionSummary(
            title="Physical Therapy",
            description="Non-invasive treatment approach",
            benefits=["Low risk", "Builds strength"],
            drawbacks=["Takes time", "Requires commitment"],
            typical_timeline="6-12 weeks",
        )

        assert option.title == "Physical Therapy"
        assert len(option.benefits) == 2
        assert len(option.drawbacks) == 2
        assert option.typical_timeline == "6-12 weeks"

    def test_conversation_summary_data_schema(self):
        """Test ConversationSummaryData schema creation."""
        from sdm_platform.memory.schemas import ConversationSummaryData
        from sdm_platform.memory.schemas import PointSummary

        point = PointSummary(
            title="Treatment Goals",
            description="Goals discussion",
            extracted_points=["Goal 1"],
            relevant_quotes=["Quote 1"],
            structured_data={},
            first_addressed_at=None,
        )

        summary_data = ConversationSummaryData(
            user_name="Jane Doe",
            preferred_name="Jane",
            journey_title="Back Pain Decision Support",
            journey_description="Journey description",
            onboarding_responses={"question1": "answer1"},
            point_summaries=[point],
            selected_option=None,
            narrative_summary="This is the narrative summary text.",
            generated_at=datetime.now(UTC),
            conversation_id="conv-123",
        )

        assert summary_data.user_name == "Jane Doe"
        assert summary_data.preferred_name == "Jane"
        assert len(summary_data.point_summaries) == 1
        assert summary_data.narrative_summary == "This is the narrative summary text."


class ConversationSummaryServiceTest(TestCase):
    """Test ConversationSummaryService."""

    def setUp(self):
        """Set up test fixtures."""
        from sdm_platform.journeys.models import Journey
        from sdm_platform.llmchat.models import Conversation
        from sdm_platform.memory.models import ConversationPoint

        self.user = User.objects.create_user(
            email="test@example.com",
            password="testpass123",
        )

        self.journey, _ = Journey.objects.get_or_create(
            slug="backpain-summary-test",
            defaults={
                "title": "Back Pain Decision Support",
                "description": "Test journey",
            },
        )

        self.conversation = Conversation.objects.create(
            user=self.user,
            journey=self.journey,
        )

        # Create conversation points
        self.point1 = ConversationPoint.objects.create(
            journey=self.journey,
            slug="treatment-goals",
            title="Treatment Goals",
            description="Discuss goals",
            system_message_template="Let's discuss your goals",
            semantic_keywords=["goals", "objectives"],
        )

        self.point2 = ConversationPoint.objects.create(
            journey=self.journey,
            slug="preferences",
            title="Treatment Preferences",
            description="Discuss preferences",
            system_message_template="Let's discuss your preferences",
            semantic_keywords=["prefer", "like"],
        )

    def test_is_complete_returns_false_when_no_memories(self):
        """Test is_complete returns False when no conversation point memories exist."""
        from sdm_platform.memory.services.summary import ConversationSummaryService

        with patch("sdm_platform.memory.managers.get_memory_store") as mock_store_ctx:
            mock_store = MagicMock()
            mock_store.search.return_value = []  # No memories
            mock_store.__enter__ = MagicMock(return_value=mock_store)
            mock_store.__exit__ = MagicMock(return_value=False)
            mock_store_ctx.return_value = mock_store

            service = ConversationSummaryService(self.conversation)
            assert service.is_complete() is False

    def test_is_complete_returns_false_when_some_points_not_addressed(self):
        """Test is_complete returns False when some points are not addressed."""
        from sdm_platform.memory.services.summary import ConversationSummaryService

        # Mock one addressed, one not addressed
        mock_item1 = MagicMock()
        mock_item1.key = "point_treatment-goals"
        mock_item1.value = {
            "conversation_point_slug": "treatment-goals",
            "journey_slug": "backpain",
            "is_addressed": True,
            "confidence_score": 0.9,
            "extracted_points": [],
            "relevant_quotes": [],
            "structured_data": {},
            "first_addressed_at": datetime.now(UTC).isoformat(),
            "last_analyzed_at": datetime.now(UTC).isoformat(),
            "message_count_analyzed": 5,
        }

        mock_item2 = MagicMock()
        mock_item2.key = "point_preferences"
        mock_item2.value = {
            "conversation_point_slug": "preferences",
            "journey_slug": "backpain",
            "is_addressed": False,
            "confidence_score": 0.2,
            "extracted_points": [],
            "relevant_quotes": [],
            "structured_data": {},
            "first_addressed_at": None,
            "last_analyzed_at": datetime.now(UTC).isoformat(),
            "message_count_analyzed": 3,
        }

        with patch("sdm_platform.memory.managers.get_memory_store") as mock_store_ctx:
            mock_store = MagicMock()
            mock_store.search.return_value = [mock_item1, mock_item2]
            mock_store.__enter__ = MagicMock(return_value=mock_store)
            mock_store.__exit__ = MagicMock(return_value=False)
            mock_store_ctx.return_value = mock_store

            service = ConversationSummaryService(self.conversation)
            assert service.is_complete() is False

    def test_is_complete_returns_true_when_all_points_addressed(self):
        """Test is_complete returns True when all conversation points are addressed."""
        from sdm_platform.memory.services.summary import ConversationSummaryService

        # Mock both points addressed
        mock_item1 = MagicMock()
        mock_item1.key = "point_treatment-goals"
        mock_item1.value = {
            "conversation_point_slug": "treatment-goals",
            "journey_slug": "backpain",
            "is_addressed": True,
            "confidence_score": 0.9,
            "extracted_points": [],
            "relevant_quotes": [],
            "structured_data": {},
            "first_addressed_at": datetime.now(UTC).isoformat(),
            "last_analyzed_at": datetime.now(UTC).isoformat(),
            "message_count_analyzed": 5,
        }

        mock_item2 = MagicMock()
        mock_item2.key = "point_preferences"
        mock_item2.value = {
            "conversation_point_slug": "preferences",
            "journey_slug": "backpain",
            "is_addressed": True,
            "confidence_score": 0.85,
            "extracted_points": [],
            "relevant_quotes": [],
            "structured_data": {},
            "first_addressed_at": datetime.now(UTC).isoformat(),
            "last_analyzed_at": datetime.now(UTC).isoformat(),
            "message_count_analyzed": 3,
        }

        with patch("sdm_platform.memory.managers.get_memory_store") as mock_store_ctx:
            mock_store = MagicMock()
            mock_store.search.return_value = [mock_item1, mock_item2]
            mock_store.__enter__ = MagicMock(return_value=mock_store)
            mock_store.__exit__ = MagicMock(return_value=False)
            mock_store_ctx.return_value = mock_store

            service = ConversationSummaryService(self.conversation)
            assert service.is_complete() is True

    def test_get_summary_data_aggregates_all_fields(self):
        """Test get_summary_data aggregates all required data."""
        from sdm_platform.journeys.models import JourneyOption
        from sdm_platform.journeys.models import JourneyResponse
        from sdm_platform.memory.services.summary import ConversationSummaryService

        # Create journey option and response
        option = JourneyOption.objects.create(
            journey=self.journey,
            slug="physical-therapy",
            title="Physical Therapy",
            description="Non-invasive treatment",
            benefits=["Low risk", "Builds strength"],
            drawbacks=["Takes time"],
            typical_timeline="6-12 weeks",
        )

        JourneyResponse.objects.create(
            user=self.user,
            journey=self.journey,
            responses={"question1": "answer1"},
            selected_option=option,
        )

        # Mock conversation point memories (for both points created in setUp)
        mock_item1 = MagicMock()
        mock_item1.key = "point_treatment-goals"
        mock_item1.value = {
            "conversation_point_slug": "treatment-goals",
            "journey_slug": "backpain-summary-test",
            "is_addressed": True,
            "confidence_score": 0.9,
            "extracted_points": ["Return to gardening"],
            "relevant_quotes": ["I miss gardening"],
            "structured_data": {"activities": ["gardening"]},
            "first_addressed_at": datetime.now(UTC).isoformat(),
            "last_analyzed_at": datetime.now(UTC).isoformat(),
            "message_count_analyzed": 5,
        }

        mock_item2 = MagicMock()
        mock_item2.key = "point_preferences"
        mock_item2.value = {
            "conversation_point_slug": "preferences",
            "journey_slug": "backpain-summary-test",
            "is_addressed": True,
            "confidence_score": 0.85,
            "extracted_points": ["Prefers non-invasive"],
            "relevant_quotes": [],
            "structured_data": {},
            "first_addressed_at": datetime.now(UTC).isoformat(),
            "last_analyzed_at": datetime.now(UTC).isoformat(),
            "message_count_analyzed": 3,
        }

        # Mock user profile
        mock_profile = UserProfileMemory(
            name="Jane Doe",
            preferred_name="Jane",
            birthday=date(1985, 3, 15),
        )

        with patch("sdm_platform.memory.managers.get_memory_store") as mock_store_ctx:
            mock_store = MagicMock()
            mock_store.search.return_value = [mock_item1, mock_item2]
            mock_store.__enter__ = MagicMock(return_value=mock_store)
            mock_store.__exit__ = MagicMock(return_value=False)
            mock_store_ctx.return_value = mock_store

            with patch(
                "sdm_platform.memory.services.summary.UserProfileManager.get_profile"
            ) as mock_get_profile:
                mock_get_profile.return_value = mock_profile

                service = ConversationSummaryService(self.conversation)
                summary_data = service.get_summary_data()

                assert summary_data.user_name == "Jane Doe"
                assert summary_data.preferred_name == "Jane"
                assert summary_data.journey_title == "Back Pain Decision Support"
                assert summary_data.onboarding_responses == {"question1": "answer1"}
                assert len(summary_data.point_summaries) == 2
                assert summary_data.selected_option is not None
                assert summary_data.selected_option.title == "Physical Therapy"


class PDFGeneratorTest(TestCase):
    """Test PDF generation functionality."""

    def setUp(self):
        """Set up test fixtures."""
        from sdm_platform.memory.schemas import ConversationSummaryData
        from sdm_platform.memory.schemas import PointSummary

        self.point1 = PointSummary(
            title="Treatment Goals",
            description="Discuss treatment goals",
            extracted_points=["Return to gardening", "Walk without pain"],
            relevant_quotes=["I really miss being able to garden"],
            structured_data={"activities": ["gardening", "walking"]},
            first_addressed_at=datetime.now(UTC),
        )

        self.summary_data = ConversationSummaryData(
            user_name="Jane Doe",
            preferred_name="Jane",
            journey_title="Back Pain Decision Support",
            journey_description="Test journey description",
            onboarding_responses={"question1": "answer1"},
            point_summaries=[self.point1],
            selected_option=None,
            narrative_summary=(
                "This is a test narrative summary. Jane discussed her treatment "
                "goals and expressed her desire to return to gardening and walking "
                "without pain."
            ),
            generated_at=datetime.now(UTC),
            conversation_id="conv-123",
        )

    def test_pdf_generator_produces_valid_pdf(self):
        """Test that PDF generator produces valid PDF bytes."""
        from sdm_platform.memory.services.pdf_generator import (
            ConversationSummaryPDFGenerator,
        )

        generator = ConversationSummaryPDFGenerator(self.summary_data)
        pdf_buffer = generator.generate()

        assert pdf_buffer is not None
        assert isinstance(pdf_buffer, BytesIO)

        # PDF should start with %PDF magic bytes
        pdf_bytes = pdf_buffer.getvalue()
        assert pdf_bytes.startswith(b"%PDF")
        assert len(pdf_bytes) > 0

    def test_pdf_generator_with_minimal_data(self):
        """Test PDF generation with minimal data (no quotes, no selected option)."""
        from sdm_platform.memory.schemas import ConversationSummaryData
        from sdm_platform.memory.schemas import PointSummary
        from sdm_platform.memory.services.pdf_generator import (
            ConversationSummaryPDFGenerator,
        )

        minimal_point = PointSummary(
            title="Goals",
            description="Goals",
            extracted_points=[],
            relevant_quotes=[],
            structured_data={},
            first_addressed_at=None,
        )

        minimal_data = ConversationSummaryData(
            user_name="John Smith",
            preferred_name=None,
            journey_title="Test Journey",
            journey_description="Description",
            onboarding_responses={},
            point_summaries=[minimal_point],
            selected_option=None,
            narrative_summary="Short summary.",
            generated_at=datetime.now(UTC),
            conversation_id="conv-456",
        )

        generator = ConversationSummaryPDFGenerator(minimal_data)
        pdf_buffer = generator.generate()

        assert pdf_buffer is not None
        pdf_bytes = pdf_buffer.getvalue()
        assert pdf_bytes.startswith(b"%PDF")

    def test_pdf_generator_with_selected_option(self):
        """Test PDF generation includes selected option."""
        from sdm_platform.memory.schemas import JourneyOptionSummary
        from sdm_platform.memory.services.pdf_generator import (
            ConversationSummaryPDFGenerator,
        )

        self.summary_data.selected_option = JourneyOptionSummary(
            title="Physical Therapy",
            description="Non-invasive treatment",
            benefits=["Low risk", "Builds strength"],
            drawbacks=["Takes time"],
            typical_timeline="6-12 weeks",
        )

        generator = ConversationSummaryPDFGenerator(self.summary_data)
        pdf_buffer = generator.generate()

        assert pdf_buffer is not None
        pdf_bytes = pdf_buffer.getvalue()
        assert pdf_bytes.startswith(b"%PDF")


class ConversationSummaryViewsTest(TestCase):
    """Test conversation summary API endpoints."""

    def setUp(self):
        """Set up test fixtures."""
        from sdm_platform.journeys.models import Journey
        from sdm_platform.llmchat.models import Conversation

        self.user = User.objects.create_user(
            email="test@example.com",
            password="testpass123",
        )

        self.other_user = User.objects.create_user(
            email="other@example.com",
            password="testpass123",
        )

        self.journey, _ = Journey.objects.get_or_create(
            slug="backpain-views-test",
            defaults={
                "title": "Back Pain Decision Support",
                "description": "Test journey",
            },
        )

        self.conversation = Conversation.objects.create(
            user=self.user,
            journey=self.journey,
        )

        self.client.force_login(self.user)

    def test_summary_status_returns_false_when_no_summary(self):
        """Test status endpoint returns ready: false when no summary exists."""
        from django.urls import reverse

        url = reverse(
            "memory:summary_status",
            args=[str(self.conversation.id)],
        )
        response = self.client.get(url)

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["ready"] is False

    def test_summary_status_returns_true_when_summary_exists(self):
        """Test status endpoint returns ready: true when summary exists."""
        from django.core.files.base import ContentFile
        from django.urls import reverse

        from sdm_platform.memory.models import ConversationSummary

        # Create a summary
        summary = ConversationSummary.objects.create(
            conversation=self.conversation,
            narrative_summary="Test summary",
        )
        summary.file.save("test.pdf", ContentFile(b"%PDF-test"))

        url = reverse(
            "memory:summary_status",
            args=[str(self.conversation.id)],
        )
        response = self.client.get(url)

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["ready"] is True
        assert "download_url" in data
        assert "generated_at" in data

    def test_summary_status_requires_authentication(self):
        """Test status endpoint requires user to be logged in."""
        from django.urls import reverse

        self.client.logout()

        url = reverse(
            "memory:summary_status",
            args=[str(self.conversation.id)],
        )
        response = self.client.get(url)

        # Should redirect to login
        assert response.status_code == 302

    def test_summary_status_requires_ownership(self):
        """Test user cannot check status of another user's conversation."""
        from django.urls import reverse

        # Login as other user
        self.client.force_login(self.other_user)

        url = reverse(
            "memory:summary_status",
            args=[str(self.conversation.id)],
        )
        response = self.client.get(url)

        # Should return 404 (conversation not found for this user)
        assert response.status_code == 404

    def test_download_summary_returns_pdf_file(self):
        """Test download endpoint returns PDF file."""
        from django.core.files.base import ContentFile
        from django.urls import reverse

        from sdm_platform.memory.models import ConversationSummary

        # Create a summary
        summary = ConversationSummary.objects.create(
            conversation=self.conversation,
            narrative_summary="Test summary",
        )
        summary.file.save("test.pdf", ContentFile(b"%PDF-test-content"))

        url = reverse(
            "memory:download_summary",
            args=[str(self.conversation.id)],
        )
        response = self.client.get(url)

        assert response.status_code == 200
        assert response["Content-Type"] == "application/pdf"
        assert "attachment" in response["Content-Disposition"]

    def test_download_summary_returns_404_when_no_summary(self):
        """Test download endpoint returns 404 when no summary exists."""
        from django.urls import reverse

        url = reverse(
            "memory:download_summary",
            args=[str(self.conversation.id)],
        )
        response = self.client.get(url)

        assert response.status_code == 404
        data = response.json()
        assert data["success"] is False
        assert "error" in data

    def test_download_summary_requires_authentication(self):
        """Test download endpoint requires authentication."""
        from django.urls import reverse

        self.client.logout()

        url = reverse(
            "memory:download_summary",
            args=[str(self.conversation.id)],
        )
        response = self.client.get(url)

        # Should redirect to login
        assert response.status_code == 302

    def test_download_summary_requires_ownership(self):
        """Test user cannot download another user's summary."""
        from django.core.files.base import ContentFile
        from django.urls import reverse

        from sdm_platform.memory.models import ConversationSummary

        # Create a summary
        summary = ConversationSummary.objects.create(
            conversation=self.conversation,
            narrative_summary="Test summary",
        )
        summary.file.save("test.pdf", ContentFile(b"%PDF-test"))

        # Login as other user
        self.client.force_login(self.other_user)

        url = reverse(
            "memory:download_summary",
            args=[str(self.conversation.id)],
        )
        response = self.client.get(url)

        # Should return 404 (conversation not found for this user)
        assert response.status_code == 404


class ConversationSummaryTaskTest(TestCase):
    """Test conversation summary generation task."""

    def setUp(self):
        """Set up test fixtures."""
        from sdm_platform.journeys.models import Journey
        from sdm_platform.journeys.models import JourneyResponse
        from sdm_platform.llmchat.models import Conversation
        from sdm_platform.memory.models import ConversationPoint

        self.user = User.objects.create_user(
            email="test@example.com",
            password="testpass123",
        )

        self.journey, _ = Journey.objects.get_or_create(
            slug="backpain-task-test",
            defaults={
                "title": "Back Pain Decision Support",
                "description": "Test journey",
            },
        )

        self.conversation = Conversation.objects.create(
            user=self.user,
            journey=self.journey,
        )

        # Create JourneyResponse linking conversation
        self.journey_response = JourneyResponse.objects.create(
            user=self.user,
            journey=self.journey,
            conversation=self.conversation,
            responses={},
        )

        self.point = ConversationPoint.objects.create(
            journey=self.journey,
            slug="treatment-goals",
            title="Treatment Goals",
            description="Discuss goals",
            system_message_template="Let's discuss your goals",
            semantic_keywords=["goals"],
        )

    @patch("sdm_platform.memory.services.narrative.generate_narrative_summary")
    @patch("sdm_platform.memory.services.pdf_generator.ConversationSummaryPDFGenerator")
    def test_task_creates_conversation_summary(self, mock_pdf_gen, mock_narrative_gen):
        """Test that task creates ConversationSummary model."""
        from sdm_platform.memory.models import ConversationSummary
        from sdm_platform.memory.tasks import generate_conversation_summary_pdf

        # Mock narrative generation
        mock_narrative_gen.return_value = "Generated narrative summary text."

        # Mock PDF generation
        mock_generator = MagicMock()
        mock_generator.generate.return_value = BytesIO(b"%PDF-mock-content")
        mock_pdf_gen.return_value = mock_generator

        # Mock summary service
        with patch(
            "sdm_platform.memory.services.summary.ConversationSummaryService"
        ) as mock_service_class:
            mock_service = MagicMock()
            mock_service.get_summary_data.return_value = MagicMock(
                narrative_summary="",
                user_name="Jane Doe",
            )
            mock_service_class.return_value = mock_service

            # Run task
            result = generate_conversation_summary_pdf(str(self.conversation.id))

            # Verify ConversationSummary was created
            assert ConversationSummary.objects.filter(
                conversation=self.conversation
            ).exists()

            summary = ConversationSummary.objects.get(conversation=self.conversation)
            assert summary.narrative_summary == "Generated narrative summary text."
            assert summary.file is not None
            assert result == str(summary.id)

    @patch("sdm_platform.memory.services.narrative.generate_narrative_summary")
    def test_task_is_idempotent(self, mock_narrative_gen):
        """Test that task doesn't recreate existing summary."""
        from sdm_platform.memory.models import ConversationSummary
        from sdm_platform.memory.tasks import generate_conversation_summary_pdf

        # Create existing summary
        existing_summary = ConversationSummary.objects.create(
            conversation=self.conversation,
            narrative_summary="Existing summary",
        )

        # Run task
        result = generate_conversation_summary_pdf(str(self.conversation.id))

        # Should return existing summary ID
        assert result == str(existing_summary.id)

        # Should NOT have called narrative generation
        mock_narrative_gen.assert_not_called()

        # Should only have one summary
        assert (
            ConversationSummary.objects.filter(conversation=self.conversation).count()
            == 1
        )

    def test_check_and_trigger_when_not_complete(self):
        """Test check_and_trigger doesn't trigger when not all points addressed."""
        from sdm_platform.memory.tasks import check_and_trigger_summary_generation

        with patch(
            "sdm_platform.memory.services.summary.ConversationSummaryService"
        ) as mock_service_class:
            mock_service = MagicMock()
            mock_service.is_complete.return_value = False
            mock_service_class.return_value = mock_service

            with patch(
                "sdm_platform.memory.tasks.generate_conversation_summary_pdf.delay"
            ) as mock_task:
                check_and_trigger_summary_generation(
                    user_id=self.user.email,
                    journey_slug="backpain-task-test",
                )

                # Task should NOT be triggered
                mock_task.assert_not_called()

    def test_check_and_trigger_when_complete(self):
        """Test check_and_trigger triggers task when all points addressed."""
        from sdm_platform.memory.tasks import check_and_trigger_summary_generation

        with patch(
            "sdm_platform.memory.services.summary.ConversationSummaryService"
        ) as mock_service_class:
            mock_service = MagicMock()
            mock_service.is_complete.return_value = True
            mock_service_class.return_value = mock_service

            with patch(
                "sdm_platform.memory.tasks.generate_conversation_summary_pdf.delay"
            ) as mock_task:
                check_and_trigger_summary_generation(
                    user_id=self.user.email,
                    journey_slug="backpain-task-test",
                )

                # Task SHOULD be triggered
                mock_task.assert_called_once_with(str(self.conversation.id))

    def test_check_and_trigger_skips_if_summary_exists(self):
        """Test check_and_trigger skips if summary already exists."""
        from sdm_platform.memory.models import ConversationSummary
        from sdm_platform.memory.tasks import check_and_trigger_summary_generation

        # Create existing summary
        ConversationSummary.objects.create(
            conversation=self.conversation,
            narrative_summary="Existing",
        )

        with patch(
            "sdm_platform.memory.tasks.generate_conversation_summary_pdf.delay"
        ) as mock_task:
            check_and_trigger_summary_generation(
                user_id=self.user.email,
                journey_slug="backpain-task-test",
            )

            # Task should NOT be triggered
            mock_task.assert_not_called()
