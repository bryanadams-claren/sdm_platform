"""Tests for Journey middleware."""

from unittest.mock import Mock

from django.test import RequestFactory
from django.test import TestCase

from sdm_platform.journeys.middleware import SubdomainJourneyMiddleware
from sdm_platform.journeys.models import Journey


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
