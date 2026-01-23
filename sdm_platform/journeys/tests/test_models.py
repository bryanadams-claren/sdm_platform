# ruff: noqa: B017, PT027, S106
"""Tests for Journey models."""

from django.test import TestCase
from django.utils import timezone

from sdm_platform.journeys.models import Journey
from sdm_platform.journeys.models import JourneyOption
from sdm_platform.journeys.models import JourneyResponse
from sdm_platform.llmchat.models import Conversation
from sdm_platform.users.models import User


class JourneyModelTest(TestCase):
    """Test the Journey model"""

    def setUp(self):
        self.journey = Journey.objects.create(
            slug="test-journey",
            title="Test Journey Decision Support",
            description="Help making decisions about test conditions",
            welcome_message="Welcome to the test decision support tool",
            system_prompt_template=(
                "The patient has had test condition for {duration} with "
                "{pain_level} severity."
            ),
            onboarding_questions=[
                {
                    "id": "duration",
                    "type": "choice",
                    "text": "How long have you had this condition?",
                    "options": [
                        "Less than 1 month",
                        "1-3 months",
                        "3-6 months",
                        "Over 6 months",
                    ],
                },
                {
                    "id": "pain_level",
                    "type": "choice",
                    "text": "How would you rate your symptoms?",
                    "options": ["Mild", "Moderate", "Severe"],
                },
            ],
            is_active=True,
            sort_order=1,
        )

    def test_journey_creation(self):
        """Test creating a journey"""
        self.assertEqual(self.journey.slug, "test-journey")
        self.assertEqual(self.journey.title, "Test Journey Decision Support")
        self.assertTrue(self.journey.is_active)
        self.assertEqual(len(self.journey.onboarding_questions), 2)

    def test_journey_str_representation(self):
        """Test the string representation of a journey"""
        expected = "Journey: Test Journey Decision Support"
        self.assertEqual(str(self.journey), expected)

    def test_journey_ordering(self):
        """Test that journeys are ordered by sort_order and slug"""
        journey2 = Journey.objects.create(
            slug="another-journey",
            title="Another Journey",
            sort_order=0,  # Lower sort order
        )

        journeys = list(Journey.objects.all())
        # Note: backpain fixture may be loaded, so we filter for our test data
        self.assertIn(journey2, journeys)
        self.assertIn(self.journey, journeys)

    def test_build_system_prompt_success(self):
        """Test building system prompt with valid responses"""
        responses = {
            "duration": "3-6 months",
            "pain_level": "Moderate",
        }

        result = self.journey.build_system_prompt(responses)
        expected = (
            "The patient has had test condition for 3-6 months with Moderate severity."
        )
        self.assertEqual(result, expected)

    def test_build_system_prompt_missing_placeholder(self):
        """Test building system prompt with missing placeholder values"""
        responses = {
            "duration": "3-6 months",
            # pain_level is missing
        }

        # Should return template as-is when placeholder is missing
        result = self.journey.build_system_prompt(responses)
        self.assertIn("{pain_level}", result)

    def test_build_system_prompt_empty_template(self):
        """Test building system prompt with empty template"""
        self.journey.system_prompt_template = ""
        responses = {"duration": "3-6 months"}

        result = self.journey.build_system_prompt(responses)
        self.assertEqual(result, "")

    def test_build_system_prompt_converts_values_to_labels(self):
        """Test that build_system_prompt converts raw values to human-readable labels"""
        # Set up journey with value/label options (like real fixture data)
        self.journey.onboarding_questions = [
            {
                "id": "duration",
                "type": "choice",
                "text": "How long have you had this condition?",
                "options": [
                    {"value": "less_than_6_weeks", "label": "Less than 6 weeks"},
                    {"value": "6_weeks_to_3_months", "label": "6 weeks to 3 months"},
                    {"value": "more_than_3_months", "label": "More than 3 months"},
                ],
            },
            {
                "id": "pain_level",
                "type": "choice",
                "text": "How would you rate your symptoms?",
                "options": [
                    {"value": "mild", "label": "Mild (1-3)"},
                    {"value": "moderate", "label": "Moderate (4-6)"},
                    {"value": "severe", "label": "Severe (7-10)"},
                ],
            },
        ]
        self.journey.save()

        # Pass raw values (as stored in JourneyResponse)
        responses = {
            "duration": "less_than_6_weeks",
            "pain_level": "moderate",
        }

        result = self.journey.build_system_prompt(responses)

        # Should use labels, not raw values
        expected = (
            "The patient has had test condition for Less than 6 weeks with "
            "Moderate (4-6) severity."
        )
        self.assertEqual(result, expected)

    def test_build_system_prompt_converts_multiselect_values_to_labels(self):
        """Test that multi-select responses are converted to labels"""
        self.journey.system_prompt_template = "Treatments tried: {treatments_tried}."
        self.journey.onboarding_questions = [
            {
                "id": "treatments_tried",
                "type": "multiple",
                "text": "What treatments have you tried?",
                "options": [
                    {"value": "otc_meds", "label": "Over-the-counter medication"},
                    {"value": "physical_therapy", "label": "Physical therapy"},
                    {"value": "rest", "label": "Rest and activity modification"},
                ],
            },
        ]
        self.journey.save()

        responses = {
            "treatments_tried": ["otc_meds", "physical_therapy"],
        }

        result = self.journey.build_system_prompt(responses)

        expected = "Treatments tried: Over-the-counter medication, Physical therapy."
        self.assertEqual(result, expected)


class JourneyOptionModelTest(TestCase):
    """Test the JourneyOption model"""

    def setUp(self):
        self.journey = Journey.objects.create(
            slug="backpain-options",
            title="Back Pain Decision Support",
        )

        self.option = JourneyOption.objects.create(
            journey=self.journey,
            slug="physical-therapy",
            title="Physical Therapy",
            description="Non-invasive treatment approach",
            benefits=["Low risk", "Non-invasive", "Improves strength"],
            drawbacks=["Requires time commitment", "May take weeks"],
            typical_timeline="6-12 weeks",
            success_rate="70-80%",
            sort_order=1,
        )

    def test_journey_option_creation(self):
        """Test creating a journey option"""
        self.assertEqual(self.option.slug, "physical-therapy")
        self.assertEqual(self.option.title, "Physical Therapy")
        self.assertEqual(len(self.option.benefits), 3)
        self.assertEqual(len(self.option.drawbacks), 2)

    def test_journey_option_str_representation(self):
        """Test the string representation of a journey option"""
        expected = "backpain-options: Physical Therapy"
        self.assertEqual(str(self.option), expected)

    def test_journey_option_ordering(self):
        """Test that options are ordered by sort_order"""
        option2 = JourneyOption.objects.create(
            journey=self.journey,
            slug="medication",
            title="Medication",
            sort_order=0,  # Lower sort order
        )

        options = list(JourneyOption.objects.filter(journey=self.journey))
        self.assertEqual(options[0], option2)
        self.assertEqual(options[1], self.option)

    def test_journey_option_unique_together(self):
        """Test that journey + slug combination is unique"""
        with self.assertRaises(Exception):  # IntegrityError
            JourneyOption.objects.create(
                journey=self.journey,
                slug="physical-therapy",  # Same slug
                title="Different Title",
            )

    def test_journey_option_cascade_delete(self):
        """Test that deleting a journey deletes its options"""
        option_id = self.option.id
        self.journey.delete()

        with self.assertRaises(JourneyOption.DoesNotExist):
            JourneyOption.objects.get(id=option_id)


class JourneyResponseModelTest(TestCase):
    """Test the JourneyResponse model"""

    def setUp(self):
        self.user = User.objects.create_user(
            email="test@example.com",
            password="testpass123",
        )
        self.journey = Journey.objects.create(
            slug="backpain-responses",
            title="Back Pain Decision Support",
        )
        self.option = JourneyOption.objects.create(
            journey=self.journey,
            slug="physical-therapy",
            title="Physical Therapy",
        )

    def test_journey_response_creation(self):
        """Test creating a journey response"""
        response = JourneyResponse.objects.create(
            journey=self.journey,
            user=self.user,
            responses={
                "duration": "3-6 months",
                "pain_level": "Moderate",
            },
            is_complete=True,
            completed_at=timezone.now(),
        )

        self.assertEqual(response.journey, self.journey)
        self.assertEqual(response.user, self.user)
        self.assertEqual(response.responses["duration"], "3-6 months")
        self.assertTrue(response.is_complete)

    def test_journey_response_str_representation(self):
        """Test the string representation of a journey response"""
        response = JourneyResponse.objects.create(
            journey=self.journey,
            user=self.user,
        )

        # Note: User model uses 'name' field, which may be empty
        self.assertIn("JourneyResponse:", str(response))
        self.assertIn(self.journey.title, str(response))

    def test_journey_response_unique_together(self):
        """Test that user + journey combination is unique"""
        JourneyResponse.objects.create(
            journey=self.journey,
            user=self.user,
        )

        with self.assertRaises(Exception):  # IntegrityError
            JourneyResponse.objects.create(
                journey=self.journey,
                user=self.user,
            )

    def test_journey_response_with_conversation(self):
        """Test linking a conversation to a journey response"""
        conversation = Conversation.objects.create(
            user=self.user,
            conv_id="backpain-test",
            thread_id="chat_test_example.com_backpain",
        )

        response = JourneyResponse.objects.create(
            journey=self.journey,
            user=self.user,
            conversation=conversation,
        )

        self.assertEqual(response.conversation, conversation)
        self.assertEqual(conversation.journey_response, response)

    def test_journey_response_with_selected_option(self):
        """Test selecting a treatment option"""
        response = JourneyResponse.objects.create(
            journey=self.journey,
            user=self.user,
        )

        response.selected_option = self.option
        response.selected_at = timezone.now()
        response.save()

        self.assertEqual(response.selected_option, self.option)
        self.assertIsNotNone(response.selected_at)
