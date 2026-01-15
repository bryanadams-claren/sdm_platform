"""Tests for onboarding email integration."""

import json

from django.core import mail
from django.test import TestCase
from django.test import override_settings
from django.urls import reverse

from sdm_platform.journeys.models import Journey
from sdm_platform.users.models import User


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class OnboardingEmailIntegrationTests(TestCase):
    """Test that onboarding flow sends welcome email."""

    def setUp(self):
        # Create a test journey
        self.journey = Journey.objects.create(
            title="Test Journey",
            slug="test",
            is_active=True,
            onboarding_questions=[{"id": "q1", "text": "Question 1", "type": "text"}],
        )

    def test_new_user_receives_welcome_email(self):
        """Test that new users receive welcome email during onboarding."""
        url = reverse("journeys:onboarding", kwargs={"journey_slug": "test"})

        data = {
            "name": "New User",
            "email": "newuser@example.com",
            "responses": {"q1": "answer1"},
        }

        response = self.client.post(
            url, data=json.dumps(data), content_type="application/json"
        )

        self.assertEqual(response.status_code, 200)

        # Check user was created
        user = User.objects.get(email="newuser@example.com")
        self.assertEqual(user.name, "New User")
        self.assertFalse(user.has_usable_password())

        # Check welcome email was sent
        self.assertEqual(len(mail.outbox), 1)
        sent_email = mail.outbox[0]
        self.assertEqual(sent_email.to, ["newuser@example.com"])
        self.assertIn("Welcome to Claren Health", sent_email.subject)

    def test_existing_user_no_welcome_email(self):
        """Test that existing users don't receive welcome email."""
        # Create existing user
        User.objects.create(email="existing@example.com", name="Existing User")

        url = reverse("journeys:onboarding", kwargs={"journey_slug": "test"})

        data = {
            "name": "Existing User",
            "email": "existing@example.com",
            "responses": {"q1": "answer1"},
        }

        response = self.client.post(
            url, data=json.dumps(data), content_type="application/json"
        )

        self.assertEqual(response.status_code, 200)

        # No email should be sent for existing user
        self.assertEqual(len(mail.outbox), 0)
