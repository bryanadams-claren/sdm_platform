"""Tests for email functionality."""

from typing import TYPE_CHECKING

from django.contrib.auth.tokens import default_token_generator
from django.core import mail
from django.test import RequestFactory
from django.test import TestCase
from django.test import override_settings
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

from sdm_platform.users.emails import send_welcome_email
from sdm_platform.users.tests.factories import UserFactory

if TYPE_CHECKING:
    from django.core.mail import EmailMultiAlternatives


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class WelcomeEmailTests(TestCase):
    """Test suite for welcome email functionality."""

    def setUp(self):
        self.factory = RequestFactory()
        self.user = UserFactory(email="test@example.com", name="Test User")

    def test_send_welcome_email_success(self):
        """Test that welcome email is sent successfully."""
        request = self.factory.get("/")
        request.META["HTTP_HOST"] = "testserver"

        result = send_welcome_email(self.user, request=request)

        self.assertTrue(result)
        self.assertEqual(len(mail.outbox), 1)

        sent_email: EmailMultiAlternatives = mail.outbox[0]  # type: ignore[assignment]
        self.assertEqual(sent_email.to, ["test@example.com"])
        self.assertIn("Welcome to Claren Health", str(sent_email.subject))
        self.assertIn("Test User", str(sent_email.body))
        self.assertIn("password/reset/key/", str(sent_email.body))

    def test_welcome_email_contains_password_reset_link(self):
        """Test that welcome email contains valid password reset link."""
        request = self.factory.get("/")
        request.META["HTTP_HOST"] = "testserver"

        send_welcome_email(self.user, request=request)

        sent_email: EmailMultiAlternatives = mail.outbox[0]  # type: ignore[assignment]

        # Generate expected token and uid
        token = default_token_generator.make_token(self.user)
        uid = urlsafe_base64_encode(force_bytes(self.user.pk))

        # Check that email contains the complete reset URL with both uid and token
        # Note: Django allauth uses hyphens in the URL format (uidb36-key)
        self.assertIn(
            f"/accounts/password/reset/key/{uid}-{token}", str(sent_email.body)
        )

    def test_welcome_email_html_alternative(self):
        """Test that welcome email has HTML alternative."""
        request = self.factory.get("/")
        request.META["HTTP_HOST"] = "testserver"

        send_welcome_email(self.user, request=request)

        sent_email: EmailMultiAlternatives = mail.outbox[0]  # type: ignore[assignment]
        self.assertEqual(len(sent_email.alternatives), 1)

        html_content, content_type = sent_email.alternatives[0]
        self.assertEqual(content_type, "text/html")
        self.assertIn(
            "<html", str(html_content)
        )  # Match opening html tag with or without attributes
        self.assertIn("Welcome to Claren Health", str(html_content))

    def test_welcome_email_without_request(self):
        """Test sending welcome email without request object."""
        result = send_welcome_email(self.user, request=None)

        self.assertTrue(result)
        self.assertEqual(len(mail.outbox), 1)

        sent_email: EmailMultiAlternatives = mail.outbox[0]  # type: ignore[assignment]
        # Should still contain password reset path
        self.assertIn("password/reset/key/", str(sent_email.body))

    def test_welcome_email_failure_handling(self):
        """Test that email sending failures are handled gracefully."""
        # Use an invalid email backend to force failure
        with override_settings(EMAIL_BACKEND="invalid.backend.DoesNotExist"):
            result = send_welcome_email(self.user, request=None)
            # Should return False but not raise exception
            self.assertFalse(result)
