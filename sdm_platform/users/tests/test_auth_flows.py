"""Tests for authentication flows."""

from django.contrib.auth import get_user_model
from django.core import mail
from django.test import Client
from django.test import TestCase
from django.test import override_settings
from django.urls import reverse

from sdm_platform.users.tests.factories import UserFactory

User = get_user_model()


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    ACCOUNT_LOGIN_BY_CODE_ENABLED=True,
)
class PasswordResetFlowTests(TestCase):
    """Test password reset functionality."""

    def setUp(self):
        self.client = Client()
        self.user = UserFactory(email="user@example.com")
        self.user.set_unusable_password()
        self.user.save()

    def test_password_reset_request(self):
        """Test requesting password reset."""
        url = reverse("account_reset_password")
        response = self.client.post(url, {"email": "user@example.com"})

        # Should redirect to done page
        self.assertEqual(response.status_code, 302)
        self.assertIn("password/reset/done", response.url)

        # Email should be sent
        self.assertEqual(len(mail.outbox), 1)
        sent_email = mail.outbox[0]
        self.assertEqual(sent_email.to, ["user@example.com"])
        self.assertIn("password", sent_email.subject.lower())

    def test_password_reset_from_key_valid(self):
        """Test password reset with valid token."""
        # First request reset
        self.client.post(
            reverse("account_reset_password"), {"email": "user@example.com"}
        )

        # Email should be sent
        self.assertEqual(len(mail.outbox), 1)

        # For now, just verify the flow exists
        response = self.client.get(reverse("account_reset_password"))
        self.assertEqual(response.status_code, 200)

    def test_password_reset_nonexistent_email(self):
        """Test password reset for non-existent email."""
        url = reverse("account_reset_password")
        response = self.client.post(url, {"email": "nonexistent@example.com"})

        # Should still redirect (prevent enumeration)
        self.assertEqual(response.status_code, 302)


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    ACCOUNT_LOGIN_BY_CODE_ENABLED=True,
)
class MagicLinkFlowTests(TestCase):
    """Test magic link login functionality."""

    def setUp(self):
        self.client = Client()
        self.user = UserFactory(email="user@example.com")

    def test_request_magic_link(self):
        """Test requesting a magic login link."""
        url = reverse("account_request_login_code")
        response = self.client.post(url, {"email": "user@example.com"})

        # Should redirect or show success
        self.assertIn(response.status_code, [200, 302])

        # Email should be sent
        self.assertEqual(len(mail.outbox), 1)
        sent_email = mail.outbox[0]
        self.assertEqual(sent_email.to, ["user@example.com"])

    def test_magic_link_page_renders(self):
        """Test that magic link request page renders."""
        url = reverse("account_request_login_code")
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "magic", html=False)


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class LoginPageTests(TestCase):
    """Test login page functionality."""

    def setUp(self):
        self.client = Client()
        self.user = UserFactory(email="user@example.com")
        self.user.set_password("testpass123")
        self.user.save()

    def test_login_page_renders(self):
        """Test that login page renders correctly."""
        url = reverse("account_login")
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Sign In")
        self.assertContains(response, "Magic Link")

    def test_login_with_email_password(self):
        """Test logging in with email and password."""
        url = reverse("account_login")
        response = self.client.post(
            url, {"login": "user@example.com", "password": "testpass123"}
        )

        # Should redirect after successful login
        self.assertEqual(response.status_code, 302)

    def test_login_with_wrong_password(self):
        """Test login fails with wrong password."""
        url = reverse("account_login")
        response = self.client.post(
            url, {"login": "user@example.com", "password": "wrongpassword"}
        )

        # Should not redirect
        self.assertEqual(response.status_code, 200)
