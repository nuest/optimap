"""Tests for harvesting provenance and user attribution."""
import os
import django
from pathlib import Path
from django.test import TestCase

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'optimap.settings')
django.setup()

from works.models import Work, Source, HarvestingEvent
from works.tasks import (
    parse_oai_xml_and_save_works,
    parse_rss_feed_and_save_publications,
    get_or_create_admin_command_user
)
from django.contrib.auth import get_user_model

User = get_user_model()
BASE_TEST_DIR = Path(__file__).resolve().parent


class HarvestingProvenanceTest(TestCase):
    """Test that harvested publications have provenance and creator information."""

    def setUp(self):
        """Set up test data."""
        self.source = Source.objects.create(
            name="Test Journal",
            url_field="https://example.com/oai",
            homepage_url="https://example.com/journal"
        )
        self.event = HarvestingEvent.objects.create(
            source=self.source,
            status="in_progress"
        )

    def test_admin_command_user_creation(self):
        """Test that the admin command user is created correctly."""
        user = get_or_create_admin_command_user()

        self.assertIsNotNone(user)
        self.assertEqual(user.username, 'django_admin_command')
        self.assertEqual(user.email, 'django_admin_command@system.local')
        self.assertFalse(user.is_active)
        self.assertFalse(user.is_staff)

        # Calling again should return the same user, not create a new one
        user2 = get_or_create_admin_command_user()
        self.assertEqual(user.id, user2.id)

    def test_oai_pmh_harvesting_sets_provenance(self):
        """Test that OAI-PMH harvesting sets provenance and created_by."""
        xml_path = BASE_TEST_DIR / 'harvesting' / 'source_1' / 'oai_dc.xml'
        xml_bytes = xml_path.read_bytes()

        parse_oai_xml_and_save_works(xml_bytes, self.event)

        # Check that publications were created
        pubs = Work.objects.filter(job=self.event)
        self.assertGreater(pubs.count(), 0, "Should have created at least one publication")

        # Check first publication
        pub = pubs.first()

        # Check created_by is set to admin command user
        self.assertIsNotNone(pub.created_by)
        self.assertEqual(pub.created_by.username, 'django_admin_command')

        # Check provenance is set
        self.assertIsNotNone(pub.provenance)
        self.assertIn('Harvested via OAI-PMH', pub.provenance)
        self.assertIn(self.source.name, pub.provenance)
        self.assertIn(self.source.url_field, pub.provenance)
        self.assertIn(f'HarvestingEvent ID: {self.event.id}', pub.provenance)

    def test_rss_harvesting_sets_provenance(self):
        """Test that RSS/Atom harvesting sets provenance and created_by."""
        rss_path = BASE_TEST_DIR / 'harvesting' / 'rss_feed_sample.xml'
        feed_url = f"file://{rss_path}"

        parse_rss_feed_and_save_publications(feed_url, self.event)

        # Check that publications were created
        pubs = Work.objects.filter(job=self.event)
        self.assertGreater(pubs.count(), 0, "Should have created at least one publication")

        # Check first publication
        pub = pubs.first()

        # Check created_by is set to admin command user
        self.assertIsNotNone(pub.created_by)
        self.assertEqual(pub.created_by.username, 'django_admin_command')

        # Check provenance is set
        self.assertIsNotNone(pub.provenance)
        self.assertIn('Harvested via RSS/Atom', pub.provenance)
        self.assertIn(self.source.name, pub.provenance)
        self.assertIn(f'HarvestingEvent ID: {self.event.id}', pub.provenance)
