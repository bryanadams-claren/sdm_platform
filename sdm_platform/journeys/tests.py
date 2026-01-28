"""Tests for the journeys app, including DecisionAid model."""

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase

from sdm_platform.journeys.models import DecisionAid
from sdm_platform.journeys.models import Journey


class DecisionAidModelTest(TestCase):
    """Test the DecisionAid model."""

    def setUp(self):
        self.journey = Journey.objects.create(
            slug="backpain",
            title="Back Pain Journey",
        )

    def test_create_decision_aid_with_external_url(self):
        """Test creating a decision aid with an external URL."""
        aid = DecisionAid.objects.create(
            slug="spine-anatomy",
            title="Spine Anatomy Diagram",
            aid_type=DecisionAid.AidType.EXTERNAL_VIDEO,
            external_url="https://www.youtube.com/watch?v=abc123",
            description="A diagram showing the spine anatomy.",
        )

        self.assertIsNotNone(aid.id)
        self.assertEqual(aid.slug, "spine-anatomy")
        self.assertEqual(aid.aid_type, DecisionAid.AidType.EXTERNAL_VIDEO)
        self.assertTrue(aid.is_active)
        self.assertEqual(aid.media_url, "https://www.youtube.com/watch?v=abc123")

    def test_create_decision_aid_with_file(self):
        """Test creating a decision aid with an uploaded file."""
        # Create a simple test file
        test_file = SimpleUploadedFile(
            name="test_image.png",
            content=b"\x89PNG\r\n\x1a\n",  # Minimal PNG header
            content_type="image/png",
        )

        aid = DecisionAid.objects.create(
            slug="test-image",
            title="Test Image",
            aid_type=DecisionAid.AidType.IMAGE,
            file=test_file,
            description="A test image.",
        )

        self.assertIsNotNone(aid.id)
        self.assertIn("decision_aids/", aid.file.name)
        # media_url should use file URL when file exists
        self.assertIn("decision_aids/", aid.media_url)

    def test_is_universal_property(self):
        """Test the is_universal property."""
        # Aid without journeys is universal
        universal_aid = DecisionAid.objects.create(
            slug="universal-aid",
            title="Universal Aid",
            aid_type=DecisionAid.AidType.DIAGRAM,
            external_url="https://example.com/diagram.png",
            description="A universal diagram.",
        )
        self.assertTrue(universal_aid.is_universal)

        # Aid with journey association is not universal
        journey_aid = DecisionAid.objects.create(
            slug="journey-aid",
            title="Journey-Specific Aid",
            aid_type=DecisionAid.AidType.IMAGE,
            external_url="https://example.com/image.png",
            description="A journey-specific image.",
        )
        journey_aid.journeys.add(self.journey)
        self.assertFalse(journey_aid.is_universal)

    def test_str_representation(self):
        """Test the string representation of a decision aid."""
        aid = DecisionAid.objects.create(
            slug="test-aid",
            title="Test Aid Title",
            aid_type=DecisionAid.AidType.VIDEO,
            external_url="https://example.com/video.mp4",
            description="Test description.",
        )

        expected = "Test Aid Title (Video)"
        self.assertEqual(str(aid), expected)

    def test_aid_type_choices(self):
        """Test all aid type choices are valid."""
        for aid_type, _ in DecisionAid.AidType.choices:
            aid = DecisionAid.objects.create(
                slug=f"test-{aid_type}",
                title=f"Test {aid_type}",
                aid_type=aid_type,
                external_url="https://example.com/media",
                description=f"Test {aid_type} aid.",
            )
            self.assertEqual(aid.aid_type, aid_type)

    def test_media_url_prefers_file_over_external(self):
        """Test that media_url returns file URL when both exist."""
        test_file = SimpleUploadedFile(
            name="test.png",
            content=b"\x89PNG\r\n\x1a\n",
            content_type="image/png",
        )

        aid = DecisionAid.objects.create(
            slug="both-urls",
            title="Both URLs",
            aid_type=DecisionAid.AidType.IMAGE,
            file=test_file,
            external_url="https://example.com/fallback.png",
            description="Test with both file and external URL.",
        )

        # Should prefer file URL
        self.assertIn("decision_aids/", aid.media_url)
        self.assertNotIn("example.com", aid.media_url)

    def test_ordering(self):
        """Test that aids are ordered by sort_order, then title."""
        aid3 = DecisionAid.objects.create(
            slug="aid-c",
            title="C Aid",
            aid_type=DecisionAid.AidType.IMAGE,
            sort_order=2,
            description="Aid C.",
        )
        aid1 = DecisionAid.objects.create(
            slug="aid-a",
            title="A Aid",
            aid_type=DecisionAid.AidType.IMAGE,
            sort_order=0,
            description="Aid A.",
        )
        aid2 = DecisionAid.objects.create(
            slug="aid-b",
            title="B Aid",
            aid_type=DecisionAid.AidType.IMAGE,
            sort_order=1,
            description="Aid B.",
        )

        aids = list(DecisionAid.objects.all())
        self.assertEqual(aids[0], aid1)
        self.assertEqual(aids[1], aid2)
        self.assertEqual(aids[2], aid3)

    def test_unique_slug(self):
        """Test that slug must be unique."""
        DecisionAid.objects.create(
            slug="unique-test",
            title="First Aid",
            aid_type=DecisionAid.AidType.IMAGE,
            description="First aid.",
        )

        with self.assertRaises(Exception):  # noqa: B017, PT027
            DecisionAid.objects.create(
                slug="unique-test",  # Same slug
                title="Second Aid",
                aid_type=DecisionAid.AidType.IMAGE,
                description="Second aid.",
            )

    def test_journey_many_to_many(self):
        """Test many-to-many relationship with journeys."""
        journey2 = Journey.objects.create(
            slug="kneepain",
            title="Knee Pain Journey",
        )

        aid = DecisionAid.objects.create(
            slug="multi-journey",
            title="Multi-Journey Aid",
            aid_type=DecisionAid.AidType.DIAGRAM,
            description="Aid for multiple journeys.",
        )

        aid.journeys.add(self.journey, journey2)
        self.assertEqual(aid.journeys.count(), 2)

        # Test reverse relation
        self.assertIn(aid, self.journey.decision_aids.all())
        self.assertIn(aid, journey2.decision_aids.all())


class DecisionAidQueryTest(TestCase):
    """Test queries for DecisionAid model."""

    def setUp(self):
        self.backpain = Journey.objects.create(slug="backpain", title="Back Pain")
        self.kneepain = Journey.objects.create(slug="kneepain", title="Knee Pain")

        # Universal aid (no journeys)
        self.universal_aid = DecisionAid.objects.create(
            slug="universal",
            title="Universal Aid",
            aid_type=DecisionAid.AidType.IMAGE,
            description="Universal aid.",
            is_active=True,
        )

        # Back pain specific
        self.backpain_aid = DecisionAid.objects.create(
            slug="backpain-specific",
            title="Back Pain Aid",
            aid_type=DecisionAid.AidType.VIDEO,
            description="Back pain specific.",
            is_active=True,
        )
        self.backpain_aid.journeys.add(self.backpain)

        # Inactive aid
        self.inactive_aid = DecisionAid.objects.create(
            slug="inactive",
            title="Inactive Aid",
            aid_type=DecisionAid.AidType.DIAGRAM,
            description="Inactive aid.",
            is_active=False,
        )

    def test_filter_active_only(self):
        """Test filtering for active aids only."""
        active_aids = DecisionAid.objects.filter(is_active=True)
        self.assertEqual(active_aids.count(), 2)
        self.assertNotIn(self.inactive_aid, active_aids)

    def test_filter_by_journey(self):
        """Test filtering aids by journey."""
        backpain_aids = DecisionAid.objects.filter(journeys=self.backpain)
        self.assertEqual(backpain_aids.count(), 1)
        self.assertIn(self.backpain_aid, backpain_aids)

    def test_query_universal_and_journey_aids(self):
        """Test querying aids that are universal OR for a specific journey."""
        from django.db.models import Q  # noqa: PLC0415

        # This is the pattern used in the context helper
        query = Q(is_active=True) & (
            Q(journeys__slug="backpain") | Q(journeys__isnull=True)
        )

        aids = DecisionAid.objects.filter(query).distinct()

        # Should include universal and backpain-specific aids
        self.assertEqual(aids.count(), 2)
        self.assertIn(self.universal_aid, aids)
        self.assertIn(self.backpain_aid, aids)
