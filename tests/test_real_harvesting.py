"""
Integration tests for harvesting real journal sources.

These tests perform actual HTTP requests to live OAI-PMH endpoints
and are skipped by default to avoid network dependencies and slow test runs.

To run these tests:
    SKIP_REAL_HARVESTING=0 python manage.py test tests.test_real_harvesting

To run a specific test:
    SKIP_REAL_HARVESTING=0 python manage.py test tests.test_real_harvesting.RealHarvestingTest.test_harvest_essd

Environment variables:
    SKIP_REAL_HARVESTING=0  - Enable real harvesting tests (default: skip)
"""

import os
import django
from unittest import skipIf
from django.test import TestCase

# bootstrap Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'optimap.settings')
django.setup()

from publications.models import Publication, Source, HarvestingEvent
from publications.tasks import harvest_oai_endpoint
from django.contrib.auth import get_user_model

User = get_user_model()

# Skip these tests by default unless SKIP_REAL_HARVESTING=0
SKIP_REAL_HARVESTING = os.environ.get('SKIP_REAL_HARVESTING', '1') == '1'
skip_reason = "Real harvesting tests disabled. Set SKIP_REAL_HARVESTING=0 to enable."


@skipIf(SKIP_REAL_HARVESTING, skip_reason)
class RealHarvestingTest(TestCase):
    """
    Integration tests for harvesting from real journal OAI-PMH endpoints.

    These tests verify that:
    1. The OAI-PMH endpoint is accessible
    2. Publications are successfully parsed and saved
    3. Metadata extraction works for real-world data
    4. The harvesting event completes successfully

    Each test limits harvesting to ~20 records to keep runtime reasonable.
    """

    def setUp(self):
        """Set up test user for harvesting events."""
        self.user = User.objects.create_user(
            username="harvesting_test_user",
            email="harvesting@test.optimap.science",
            password="test_password"
        )

    def tearDown(self):
        """Clean up created publications and sources."""
        Publication.objects.filter(source__name__startswith="TEST: ").delete()
        Source.objects.filter(name__startswith="TEST: ").delete()

    def _create_source(self, name, url, collection_name=None):
        """Helper to create a test source."""
        return Source.objects.create(
            name=f"TEST: {name}",
            url_field=url,
            collection_name=collection_name or name,
            harvest_interval_minutes=60 * 24 * 7  # Weekly
        )

    def _assert_successful_harvest(self, source, min_publications=1):
        """
        Assert that harvesting completed successfully with expected results.

        Args:
            source: Source model instance
            min_publications: Minimum number of publications expected
        """
        # Get the latest harvesting event
        event = HarvestingEvent.objects.filter(source=source).latest("started_at")

        # Check event completed successfully
        self.assertEqual(
            event.status,
            "completed",
            f"Harvesting event failed with status: {event.status}"
        )
        self.assertIsNotNone(event.completed_at, "Harvesting event has no completion time")

        # Check publications were created
        pub_count = Publication.objects.filter(job=event).count()
        self.assertGreaterEqual(
            pub_count,
            min_publications,
            f"Expected at least {min_publications} publications, got {pub_count}"
        )

        # Check that publications have required fields
        pubs = Publication.objects.filter(job=event)
        for pub in pubs[:5]:  # Check first 5
            self.assertTrue(
                pub.title,
                f"Publication {pub.id} missing title"
            )
            # DOI is optional but should be present for most journals
            # Geometry and temporal data are optional

        return pub_count

    def test_harvest_essd(self):
        """
        Test harvesting from Earth System Science Data (ESSD).

        Issue: https://github.com/GeoinformationSystems/optimap/issues/59
        Journal: https://essd.copernicus.org/
        """
        source = self._create_source(
            name="Earth System Science Data",
            url="https://oai-pmh.copernicus.org/oai.php",
            collection_name="ESSD"
        )

        # Harvest with limit of 20 records
        harvest_oai_endpoint(source.id, user=self.user, max_records=20)

        # Verify successful harvest
        pub_count = self._assert_successful_harvest(source, min_publications=10)
        print(f"\n✓ ESSD: Harvested {pub_count} publications")

    def test_harvest_agile_giss(self):
        """
        Test harvesting from AGILE-GISS conference series.

        Issue: https://github.com/GeoinformationSystems/optimap/issues/60
        Journal: https://www.agile-giscience-series.net/
        """
        source = self._create_source(
            name="AGILE-GISS",
            url="https://oai-pmh.copernicus.org/oai.php",
            collection_name="AGILE-GISS"
        )

        # Harvest with limit of 20 records
        harvest_oai_endpoint(source.id, user=self.user, max_records=20)

        # Verify successful harvest
        pub_count = self._assert_successful_harvest(source, min_publications=10)
        print(f"\n✓ AGILE-GISS: Harvested {pub_count} publications")

    def test_harvest_geo_leo(self):
        """
        Test harvesting from GEO-LEO e-docs repository.

        Issue: https://github.com/GeoinformationSystems/optimap/issues/13
        Repository: https://e-docs.geo-leo.de/
        """
        source = self._create_source(
            name="GEO-LEO e-docs",
            url="https://e-docs.geo-leo.de/server/oai/request",
            collection_name="GEO-LEO"
        )

        # Harvest with limit of 20 records
        harvest_oai_endpoint(source.id, user=self.user, max_records=20)

        # Verify successful harvest
        pub_count = self._assert_successful_harvest(source, min_publications=5)
        print(f"\n✓ GEO-LEO: Harvested {pub_count} publications")

    @skipIf(True, "EssOAr OAI-PMH endpoint not yet confirmed")
    def test_harvest_essoar(self):
        """
        Test harvesting from ESS Open Archive (EssOAr).

        Issue: https://github.com/GeoinformationSystems/optimap/issues/99
        Repository: https://essopenarchive.org/

        Note: OAI-PMH endpoint needs to be confirmed.
        """
        # Placeholder - needs endpoint URL
        source = self._create_source(
            name="ESS Open Archive",
            url="https://essopenarchive.org/oai/request",  # To be confirmed
            collection_name="EssOAr"
        )

        harvest_oai_endpoint(source.id, user=self.user, max_records=20)
        pub_count = self._assert_successful_harvest(source, min_publications=5)
        print(f"\n✓ EssOAr: Harvested {pub_count} publications")

    def test_harvest_respects_max_records(self):
        """
        Test that max_records parameter properly limits harvesting.

        Uses ESSD as a test source known to have many records.
        """
        source = self._create_source(
            name="ESSD (limited)",
            url="https://oai-pmh.copernicus.org/oai.php",
            collection_name="ESSD"
        )

        # Harvest with very small limit
        max_records = 5
        harvest_oai_endpoint(source.id, user=self.user, max_records=max_records)

        # Verify we got exactly the requested number (or slightly more due to batching)
        event = HarvestingEvent.objects.filter(source=source).latest("started_at")
        pub_count = Publication.objects.filter(job=event).count()

        self.assertLessEqual(
            pub_count,
            max_records + 10,  # Allow some tolerance for batch processing
            f"Harvested {pub_count} publications, expected around {max_records}"
        )
        print(f"\n✓ max_records: Harvested {pub_count} publications (limit was {max_records})")

    def test_harvest_with_metadata_extraction(self):
        """
        Test that spatial/temporal metadata is extracted when available.

        Uses GEO-LEO which should have some geospatial metadata.
        """
        source = self._create_source(
            name="GEO-LEO (metadata test)",
            url="https://e-docs.geo-leo.de/server/oai/request",
            collection_name="GEO-LEO"
        )

        harvest_oai_endpoint(source.id, user=self.user, max_records=20)

        event = HarvestingEvent.objects.filter(source=source).latest("started_at")
        pubs = Publication.objects.filter(job=event)

        # Check if any publications have spatial metadata
        spatial_count = pubs.exclude(geometry__isnull=True).count()

        # Check if any publications have temporal metadata
        temporal_count = pubs.exclude(timeperiod_startdate=[]).count()

        print(f"\n✓ Metadata extraction: {spatial_count} with geometry, "
              f"{temporal_count} with temporal data out of {pubs.count()} total")

        # We don't assert specific counts since metadata availability varies,
        # but we verify the harvesting completed successfully
        self.assertEqual(event.status, "completed")
