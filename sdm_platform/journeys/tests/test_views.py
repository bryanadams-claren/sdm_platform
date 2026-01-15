# ruff: noqa: S106
"""Tests for Journey views."""

import json
from unittest.mock import Mock

from django.test import Client
from django.test import RequestFactory
from django.test import TestCase
from django.urls import reverse

from sdm_platform.journeys.models import Journey
from sdm_platform.journeys.models import JourneyResponse
from sdm_platform.journeys.views import journey_subdomain_landing
from sdm_platform.journeys.views import journey_subdomain_onboarding
from sdm_platform.users.models import User


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
