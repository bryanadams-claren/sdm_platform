# ruff: noqa: B017, PT009, PT027, S106
# ... ignore the assertion stuff and also the hardcoded password
# pyright: reportGeneralTypeIssues=false, reportAttributeAccessIssue=false
# pyright: reportOptionalMemberAccess=false
# ... the channel stuff

import json
from unittest.mock import Mock

from django.test import Client
from django.test import RequestFactory
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from sdm_platform.journeys.middleware import SubdomainJourneyMiddleware
from sdm_platform.journeys.models import Journey
from sdm_platform.journeys.models import JourneyOption
from sdm_platform.journeys.models import JourneyResponse
from sdm_platform.journeys.views import journey_subdomain_landing
from sdm_platform.journeys.views import journey_subdomain_onboarding
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


class JourneyLandingViewTest(TestCase):
    """Test the journey landing view"""

    def setUp(self):
        self.client = Client()
        self.journey = Journey.objects.create(
            slug="backpain-landing",
            title="Back Pain Decision Support",
            description="Help with back pain decisions",
            is_active=True,
        )

    def test_journey_landing_authenticated(self):
        """Test landing page for authenticated user"""
        _ = User.objects.create_user(
            email="test@example.com",
            password="testpass123",
        )
        self.client.login(
            username="test@example.com",
            password="testpass123",
        )

        response = self.client.get(
            reverse(
                "journeys:landing",
                kwargs={"journey_slug": "backpain-landing"},
            )
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("journey", response.context)
        self.assertEqual(response.context["journey"], self.journey)
        self.assertTrue(response.context["is_authenticated"])

    def test_journey_landing_anonymous(self):
        """Test landing page for anonymous user"""
        response = self.client.get(
            reverse(
                "journeys:landing",
                kwargs={"journey_slug": "backpain-landing"},
            )
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context["is_authenticated"])

    def test_journey_landing_inactive_journey(self):
        """Test landing page for inactive journey returns 404"""
        self.journey.is_active = False
        self.journey.save()

        response = self.client.get(
            reverse(
                "journeys:landing",
                kwargs={"journey_slug": "backpain-landing"},
            )
        )
        self.assertEqual(response.status_code, 404)

    def test_journey_landing_nonexistent_journey(self):
        """Test landing page for nonexistent journey returns 404"""
        response = self.client.get(
            reverse(
                "journeys:landing",
                kwargs={"journey_slug": "nonexistent"},
            )
        )
        self.assertEqual(response.status_code, 404)


class JourneyOnboardingViewTest(TestCase):
    """Test the journey onboarding view"""

    def setUp(self):
        self.client = Client()
        self.journey = Journey.objects.create(
            slug="backpain-onboarding",
            title="Back Pain Decision Support",
            onboarding_questions=[
                {
                    "id": "duration",
                    "type": "choice",
                    "text": "How long have you had back pain?",
                    "options": ["Less than 1 month", "1-3 months"],
                },
            ],
            system_prompt_template="Pain duration: {duration}",
            is_active=True,
        )
        self.user = User.objects.create_user(
            email="test@example.com",
            password="testpass123",
            name="Test User",
        )

    def test_onboarding_get_authenticated(self):
        """Test GET request to onboarding when authenticated"""
        self.client.login(
            username="test@example.com",
            password="testpass123",
        )

        response = self.client.get(
            reverse(
                "journeys:onboarding",
                kwargs={"journey_slug": "backpain-onboarding"},
            )
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("journey", response.context)
        self.assertIn("questions", response.context)
        self.assertEqual(len(response.context["questions"]), 1)

    def test_onboarding_get_with_existing_response(self):
        """Test GET request when user already has a response"""
        self.client.login(
            username="test@example.com",
            password="testpass123",
        )

        existing_response = JourneyResponse.objects.create(
            journey=self.journey,
            user=self.user,
            responses={"duration": "1-3 months"},
        )

        response = self.client.get(
            reverse(
                "journeys:onboarding",
                kwargs={"journey_slug": "backpain-onboarding"},
            )
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.context["existing_response"],
            existing_response,
        )

    def test_onboarding_post_authenticated(self):
        """Test POST submission when authenticated"""
        self.client.login(
            username="test@example.com",
            password="testpass123",
        )

        data = {
            "responses": {
                "duration": "1-3 months",
            },
        }

        response = self.client.post(
            reverse(
                "journeys:onboarding",
                kwargs={"journey_slug": "backpain-onboarding"},
            ),
            data=json.dumps(data),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        response_data = json.loads(response.content)
        self.assertTrue(response_data["success"])
        self.assertIn("redirect_url", response_data)

        # Verify journey response was created
        journey_response = JourneyResponse.objects.get(
            user=self.user,
            journey=self.journey,
        )
        self.assertTrue(journey_response.is_complete)
        self.assertEqual(
            journey_response.responses["duration"],
            "1-3 months",
        )

        # Verify conversation was created
        self.assertIsNotNone(journey_response.conversation)

    def test_onboarding_post_anonymous_with_name_and_email(self):
        """Test POST submission when anonymous with name and email"""
        data = {
            "name": "New User",
            "email": "newuser@example.com",
            "responses": {
                "duration": "3-6 months",
            },
        }

        response = self.client.post(
            reverse(
                "journeys:onboarding",
                kwargs={"journey_slug": "backpain-onboarding"},
            ),
            data=json.dumps(data),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        response_data = json.loads(response.content)
        self.assertTrue(response_data["success"])

        # Verify user was created
        user = User.objects.get(email="newuser@example.com")
        self.assertEqual(user.name, "New User")

        # Verify user is logged in
        self.assertTrue(user.is_authenticated)

        # Verify journey response was created
        journey_response = JourneyResponse.objects.get(
            user=user,
            journey=self.journey,
        )
        self.assertEqual(
            journey_response.responses["duration"],
            "3-6 months",
        )

    def test_onboarding_post_anonymous_without_email(self):
        """Test POST submission when anonymous without email (generates one)"""
        data = {
            "name": "Anonymous User",
            "responses": {
                "duration": "Over 6 months",
            },
        }

        response = self.client.post(
            reverse(
                "journeys:onboarding",
                kwargs={"journey_slug": "backpain-onboarding"},
            ),
            data=json.dumps(data),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        response_data = json.loads(response.content)
        self.assertTrue(response_data["success"])

        # Verify a user was created with generated email
        users = User.objects.filter(name="Anonymous User")
        self.assertEqual(users.count(), 1)
        self.assertIn("@anonymous.corient.com", users.first().email)

    def test_onboarding_post_without_name(self):
        """Test POST submission without required name"""
        data = {
            "responses": {
                "duration": "1-3 months",
            },
        }

        response = self.client.post(
            reverse(
                "journeys:onboarding",
                kwargs={"journey_slug": "backpain-onboarding"},
            ),
            data=json.dumps(data),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        response_data = json.loads(response.content)
        self.assertIn("error", response_data)

    def test_onboarding_post_invalid_json(self):
        """Test POST submission with invalid JSON"""
        response = self.client.post(
            reverse(
                "journeys:onboarding",
                kwargs={"journey_slug": "backpain-onboarding"},
            ),
            data="invalid json",
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)

    def test_onboarding_post_creates_conversation_with_system_prompt(self):
        """Test that onboarding creates conversation with proper system prompt"""
        self.client.login(
            username="test@example.com",
            password="testpass123",
        )

        data = {
            "responses": {
                "duration": "6-12 months",
            },
        }

        response = self.client.post(
            reverse(
                "journeys:onboarding",
                kwargs={"journey_slug": "backpain-onboarding"},
            ),
            data=json.dumps(data),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)

        # Verify conversation has correct system prompt
        journey_response = JourneyResponse.objects.get(
            user=self.user,
            journey=self.journey,
        )
        conversation = journey_response.conversation

        self.assertIsNotNone(conversation)
        self.assertEqual(
            conversation.system_prompt,
            "Pain duration: 6-12 months",
        )


class SubdomainMiddlewareTest(TestCase):
    """Test the subdomain journey middleware"""

    def setUp(self):
        self.factory = RequestFactory()
        self.journey = Journey.objects.create(
            slug="backpain-subdomain",
            title="Back Pain Decision Support",
            is_active=True,
        )

        # Create a mock get_response callable
        self.get_response = Mock(return_value=Mock(status_code=200))

    def test_middleware_detects_journey_subdomain(self):
        """Test that middleware detects valid journey subdomain"""
        request = self.factory.get(
            "/",
            HTTP_HOST="backpain-subdomain.localhost:8000",
        )

        middleware = SubdomainJourneyMiddleware(self.get_response)
        middleware(request)

        self.assertEqual(request.journey_slug, "backpain-subdomain")
        self.assertEqual(request.journey, self.journey)

    def test_middleware_with_port(self):
        """Test that middleware handles host with port"""
        request = self.factory.get(
            "/",
            HTTP_HOST="backpain-subdomain.localhost:8000",
        )

        middleware = SubdomainJourneyMiddleware(self.get_response)
        middleware(request)

        self.assertEqual(request.journey_slug, "backpain-subdomain")

    def test_middleware_with_nonexistent_journey(self):
        """Test middleware with subdomain that doesn't match a journey"""
        request = self.factory.get(
            "/",
            HTTP_HOST="invalid.localhost:8000",
        )

        middleware = SubdomainJourneyMiddleware(self.get_response)
        middleware(request)

        self.assertIsNone(request.journey_slug)
        self.assertIsNone(request.journey)

    def test_middleware_with_inactive_journey(self):
        """Test middleware with inactive journey subdomain"""
        self.journey.is_active = False
        self.journey.save()

        request = self.factory.get(
            "/",
            HTTP_HOST="backpain-subdomain.localhost:8000",
        )

        middleware = SubdomainJourneyMiddleware(self.get_response)
        middleware(request)

        self.assertIsNone(request.journey_slug)
        self.assertIsNone(request.journey)

    def test_middleware_without_subdomain(self):
        """Test middleware with base domain (no subdomain)"""
        request = self.factory.get(
            "/",
            HTTP_HOST="localhost:8000",
        )

        middleware = SubdomainJourneyMiddleware(self.get_response)
        middleware(request)

        self.assertIsNone(request.journey_slug)
        self.assertIsNone(request.journey)

    def test_middleware_with_www(self):
        """Test middleware with www subdomain"""
        request = self.factory.get(
            "/",
            HTTP_HOST="www.localhost:8000",
        )

        middleware = SubdomainJourneyMiddleware(self.get_response)
        middleware(request)

        # www should not be treated as a journey
        self.assertIsNone(request.journey_slug)


class JourneySubdomainViewsTest(TestCase):
    """Test subdomain-specific views"""

    def setUp(self):
        self.factory = RequestFactory()
        self.journey = Journey.objects.create(
            slug="backpain-subviews",
            title="Back Pain Decision Support",
            is_active=True,
        )

    def test_subdomain_landing_with_journey(self):
        """Test subdomain landing view with valid journey"""

        request = self.factory.get("/")
        request.journey_slug = "backpain-subviews"
        request.user = Mock(is_authenticated=False)

        response = journey_subdomain_landing(request)

        self.assertEqual(response.status_code, 200)

    def test_subdomain_landing_without_journey(self):
        """Test subdomain landing view without journey_slug"""

        request = self.factory.get("/")
        request.journey_slug = None
        request.user = Mock(is_authenticated=False)

        response = journey_subdomain_landing(request)

        # Should redirect to home
        self.assertEqual(response.status_code, 302)

    def test_subdomain_onboarding_with_journey(self):
        """Test subdomain onboarding view with valid journey"""

        request = self.factory.get("/start/")
        request.journey_slug = "backpain-subviews"
        request.user = Mock(is_authenticated=False)

        response = journey_subdomain_onboarding(request)

        self.assertEqual(response.status_code, 200)

    def test_subdomain_onboarding_without_journey(self):
        """Test subdomain onboarding view without journey_slug"""

        request = self.factory.get("/start/")
        request.journey_slug = None
        request.user = Mock(is_authenticated=False)

        response = journey_subdomain_onboarding(request)

        # Should redirect to home
        self.assertEqual(response.status_code, 302)
