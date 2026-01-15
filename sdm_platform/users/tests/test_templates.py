"""Tests for authentication templates."""

from django.test import Client
from django.test import TestCase
from django.urls import reverse


class AuthenticationTemplateTests(TestCase):
    """Test that authentication templates render correctly."""

    def setUp(self):
        self.client = Client()

    def test_login_template_extends_base(self):
        """Test that login template extends base.html."""
        response = self.client.get(reverse("account_login"))
        self.assertEqual(response.status_code, 200)

        # Check for base.html elements
        self.assertContains(response, "Claren Health")
        self.assertContains(response, "navbar")

    def test_password_reset_template_extends_base(self):
        """Test that password reset template extends base.html."""
        response = self.client.get(reverse("account_reset_password"))
        self.assertEqual(response.status_code, 200)

        # Check for base.html elements
        self.assertContains(response, "Claren Health")

    def test_magic_link_template_extends_base(self):
        """Test that magic link template extends base.html."""
        response = self.client.get(reverse("account_request_login_code"))
        self.assertEqual(response.status_code, 200)

        # Check for base.html elements
        self.assertContains(response, "Claren Health")

    def test_login_page_has_magic_link_button(self):
        """Test that login page includes magic link option."""
        response = self.client.get(reverse("account_login"))
        self.assertContains(response, "Email Me a Magic Link")
        self.assertContains(response, reverse("account_request_login_code"))

    def test_login_page_has_password_reset_link(self):
        """Test that login page includes password reset link."""
        response = self.client.get(reverse("account_login"))
        self.assertContains(response, "Forgot your password")
        self.assertContains(response, reverse("account_reset_password"))
