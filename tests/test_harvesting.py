import os
import django
import time
import responses
from pathlib import Path
from django.test import Client, TestCase

# bootstrap Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'optimap.settings')
django.setup()

from publications.models import Publication, Source, HarvestingEvent, Schedule
from publications.tasks import (
    parse_oai_xml_and_save_publications,
    harvest_oai_endpoint,
    parse_rss_feed_and_save_publications,
    harvest_rss_endpoint
)
from django.contrib.auth import get_user_model

User = get_user_model()
BASE_TEST_DIR = Path(__file__).resolve().parent

class SimpleTest(TestCase):

    @responses.activate
    def setUp(self):
        super().setUp()

        Publication.objects.all().delete()

        article01_path = BASE_TEST_DIR / 'harvesting' / 'source_1' / 'article_01.html'
        article02_path = BASE_TEST_DIR / 'harvesting' / 'source_1' / 'article_02.html'
        with open(article01_path) as f1, open(article02_path) as f2:
            responses.add(
                responses.GET,
                'http://localhost:8330/index.php/opti-geo/article/view/1',
                body=f1.read()
            )
            responses.add(
                responses.GET,
                'http://localhost:8330/index.php/opti-geo/article/view/2',
                body=f2.read()
            )

        src = Source.objects.create(
            url_field="http://example.org/oai",
            harvest_interval_minutes=60
        )
        event = HarvestingEvent.objects.create(source=src, status="in_progress")

        oai_path = BASE_TEST_DIR / 'harvesting' / 'source_1' / 'oai_dc.xml'
        xml_bytes = oai_path.read_bytes()
        parse_oai_xml_and_save_publications(xml_bytes, event)

        Publication.objects.all().update(status="p")

        self.user = User.objects.create_user(
            username="testuser",
            email="testuser@example.com",
            password="password123"
        )
        self.client = Client()

        results = self.client.get('/api/v1/publications/').json()['results']
        features = results.get('features', [])
        if len(features) >= 2:
            self.id1, self.id2 = features[1]['id'], features[0]['id']
        elif len(features) == 1:
            self.id1 = self.id2 = features[0]['id']
        else:
            self.id1 = self.id2 = None

    def test_api_root(self):
        response = self.client.get('/api/v1/publications/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get('Content-Type'), 'application/json')
        results = response.json()['results']
        self.assertEqual(results['type'], 'FeatureCollection')
        self.assertEqual(len(results['features']), 2)

    def test_api_publication_1(self):
        response = self.client.get(f'/api/v1/publications/{self.id1}.json')
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body['type'], 'Feature')
        self.assertEqual(body['geometry']['type'], 'GeometryCollection')
        self.assertEqual(body['geometry']['geometries'][0]['type'], 'LineString')
        self.assertEqual(body['properties']['title'], 'Test 1: One')
        self.assertEqual(body['properties']['publicationDate'], '2022-07-01')
        self.assertEqual(body['properties']['timeperiod_startdate'], ['2022-06-01'])
        self.assertEqual(
            body['properties']['url'],
            'http://localhost:8330/index.php/opti-geo/article/view/1'
        )

    def test_api_publication_2(self):
        response = self.client.get(f'/api/v1/publications/{self.id2}.json')
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body['type'], 'Feature')
        self.assertEqual(body['geometry']['type'], 'GeometryCollection')
        self.assertEqual(body['geometry']['geometries'][0]['type'], 'Polygon')
        self.assertEqual(body['properties']['title'], 'Test 2: Two')
        self.assertIsNone(body['properties']['doi'])
        self.assertEqual(body['properties']['timeperiod_enddate'], ['2022-03-31'])
        self.assertEqual(
            body['properties']['url'],
            'http://localhost:8330/index.php/opti-geo/article/view/2'
        )

        props = body['properties']
        self.assertEqual(props['title'], 'Test 2: Two')
        self.assertIsNone(props['doi'])
        self.assertEqual(props['timeperiod_enddate'], ['2022-03-31'])
        self.assertEqual(
            props['url'],
            'http://localhost:8330/index.php/opti-geo/article/view/2'
        )

    def test_task_scheduling(self):
        oai_file_path = BASE_TEST_DIR / "harvesting" / "journal_1" / "oai_dc.xml"
        new_src = Source.objects.create(
            url_field=f"file://{oai_file_path}",
            harvest_interval_minutes=60
        )
        time.sleep(2)
        schedule_q = Schedule.objects.filter(name=f"Harvest Source {new_src.id}")
        self.assertTrue(schedule_q.exists(), "Django-Q task not scheduled for source.")

    def test_no_duplicates(self):
        publications = Publication.objects.all()
        self.assertEqual(publications.count(), 2, "Expected exactly 2 unique publications")
        titles = [p.title for p in publications]
        self.assertEqual(len(titles), len(set(titles)), "Duplicate titles found")

    def test_invalid_xml_input(self):
        src = Source.objects.create(
            url_field="http://example.org/invalid",
            harvest_interval_minutes=60
        )
        event = HarvestingEvent.objects.create(source=src, status="in_progress")

        invalid_xml = b'<invalid>malformed xml without proper closing'
        initial_count = Publication.objects.count()

        parse_oai_xml_and_save_publications(invalid_xml, event)

        self.assertEqual(Publication.objects.count(), initial_count)

    def test_empty_xml_input(self):
        """Test harvesting with empty XML input"""
        src = Source.objects.create(
            url_field="http://example.org/empty",
            harvest_interval_minutes=60
        )
        event = HarvestingEvent.objects.create(source=src, status="in_progress")

        empty_xml = b''
        initial_count = Publication.objects.count()

        parse_oai_xml_and_save_publications(empty_xml, event)

        self.assertEqual(Publication.objects.count(), initial_count)

    def test_xml_with_no_records(self):
        """Test harvesting with valid XML but no record elements"""
        src = Source.objects.create(
            url_field="http://example.org/norecords",
            harvest_interval_minutes=60
        )
        event = HarvestingEvent.objects.create(source=src, status="in_progress")

        no_records_xml = b'''<?xml version="1.0" encoding="UTF-8"?>
        <OAI-PMH xmlns="http://www.openarchives.org/OAI/2.0/">
            <responseDate>2024-01-01T00:00:00Z</responseDate>
            <request verb="ListRecords">http://example.org/oai</request>
            <ListRecords>
                <!-- No record elements -->
            </ListRecords>
        </OAI-PMH>'''

        initial_count = Publication.objects.count()

        parse_oai_xml_and_save_publications(no_records_xml, event)

        self.assertEqual(Publication.objects.count(), initial_count)

    def test_xml_with_invalid_record_data(self):
        src = Source.objects.create(
            url_field="http://example.org/invaliddata",
            harvest_interval_minutes=60
        )
        event = HarvestingEvent.objects.create(source=src, status="in_progress")

        # XML with record but missing required fields
        invalid_data_xml = b'''<?xml version="1.0" encoding="UTF-8"?>
        <OAI-PMH xmlns="http://www.openarchives.org/OAI/2.0/">
            <responseDate>2024-01-01T00:00:00Z</responseDate>
            <request verb="ListRecords">http://example.org/oai</request>
            <ListRecords>
                <record>
                    <header>
                        <identifier>oai:example.org:123</identifier>
                        <datestamp>2024-01-01</datestamp>
                    </header>
                    <metadata>
                        <oai_dc:dc xmlns:oai_dc="http://www.openarchives.org/OAI/2.0/oai_dc/"
                                   xmlns:dc="http://purl.org/dc/elements/1.1/">
                            <!-- Missing title and identifier -->
                            <dc:description>Some description</dc:description>
                        </oai_dc:dc>
                    </metadata>
                </record>
            </ListRecords>
        </OAI-PMH>'''

        initial_count = Publication.objects.count()

        parse_oai_xml_and_save_publications(invalid_data_xml, event)

        self.assertEqual(Publication.objects.count(), initial_count)

    def test_real_journal_harvesting_essd(self):
        """Test harvesting from actual ESSD Copernicus endpoint"""
        from publications.tasks import harvest_oai_endpoint

        # Clear existing publications for clean test
        Publication.objects.all().delete()

        src = Source.objects.create(
            url_field="https://oai-pmh.copernicus.org/oai.php?verb=ListRecords&metadataPrefix=oai_dc&set=essd",
            harvest_interval_minutes=1440,
            name="ESSD Copernicus"
        )

        initial_count = Publication.objects.count()

        # Harvest from real endpoint with limit
        harvest_oai_endpoint(src.id, max_records=3)

        # Should have harvested some publications
        final_count = Publication.objects.count()
        self.assertGreater(final_count, initial_count, "Should harvest at least some publications from ESSD")
        self.assertLessEqual(final_count - initial_count, 3, "Should not exceed max_records limit")

        # Verify ESSD publications were created
        essd_pubs = Publication.objects.filter(source=src)
        for pub in essd_pubs:
            self.assertIsNotNone(pub.title, f"Publication {pub.id} missing title")
            self.assertIsNotNone(pub.url, f"Publication {pub.id} missing URL")
            # ESSD should have DOIs with Copernicus prefix
            if pub.doi:
                self.assertIn("10.5194", pub.doi, "ESSD DOIs should contain Copernicus prefix")

    def test_real_journal_harvesting_geo_leo(self):
        """Test harvesting from actual GEO-LEO e-docs endpoint"""
        from publications.tasks import harvest_oai_endpoint

        # Clear existing publications for clean test
        Publication.objects.all().delete()

        src = Source.objects.create(
            url_field="https://e-docs.geo-leo.de/server/oai/request",
            harvest_interval_minutes=1440,
            name="GEO-LEO e-docs"
        )

        initial_count = Publication.objects.count()

        # Harvest from real endpoint with limit
        harvest_oai_endpoint(src.id, max_records=5)

        # Should have harvested some publications
        final_count = Publication.objects.count()
        self.assertGreater(final_count, initial_count, "Should harvest at least some publications from GEO-LEO")
        self.assertLessEqual(final_count - initial_count, 5, "Should not exceed max_records limit")

        # Verify GEO-LEO publications were created
        geo_leo_pubs = Publication.objects.filter(source=src)
        for pub in geo_leo_pubs:
            self.assertIsNotNone(pub.title, f"Publication {pub.id} missing title")
            self.assertIsNotNone(pub.url, f"Publication {pub.id} missing URL")

    def test_real_journal_harvesting_agile_giss(self):
        """Test harvesting from actual AGILE-GISS endpoint"""
        from publications.tasks import harvest_oai_endpoint

        # Clear existing publications for clean test
        Publication.objects.all().delete()

        src = Source.objects.create(
            url_field="https://www.agile-giscience-series.net",
            harvest_interval_minutes=1440,
            name="AGILE-GISS"
        )

        initial_count = Publication.objects.count()

        # Note: This may fail if AGILE doesn't have OAI-PMH endpoint
        try:
            harvest_oai_endpoint(src.id, max_records=3)

            # Should have harvested some publications
            final_count = Publication.objects.count()
            self.assertGreater(final_count, initial_count, "Should harvest at least some publications from AGILE-GISS")
            self.assertLessEqual(final_count - initial_count, 3, "Should not exceed max_records limit")

            # Verify AGILE publications were created
            agile_pubs = Publication.objects.filter(source=src)
            for pub in agile_pubs:
                self.assertIsNotNone(pub.title, f"Publication {pub.id} missing title")
                self.assertIsNotNone(pub.url, f"Publication {pub.id} missing URL")
        except Exception as e:
            # Skip test if AGILE doesn't have OAI-PMH endpoint
            self.skipTest(f"AGILE-GISS endpoint not available: {e}")


class HarvestingErrorTests(TestCase):
    """
    Test cases for error handling during harvesting.

    These tests verify that the harvesting system properly handles:
    - Malformed XML
    - Empty responses
    - Missing required metadata
    - Invalid XML structure
    - Network/HTTP errors
    """

    def setUp(self):
        """Set up test sources and events."""
        Publication.objects.all().delete()
        self.source = Source.objects.create(
            url_field="http://example.com/oai",
            harvest_interval_minutes=60,
            name="Error Test Source"
        )

    def test_malformed_xml(self):
        """Test that malformed XML is handled gracefully."""
        event = HarvestingEvent.objects.create(
            source=self.source,
            status="in_progress"
        )

        malformed_xml_path = BASE_TEST_DIR / 'harvesting' / 'error_cases' / 'malformed_xml.xml'
        xml_bytes = malformed_xml_path.read_bytes()

        # Should not raise exception, but should log error
        parse_oai_xml_and_save_publications(xml_bytes, event)

        # No publications should be created from malformed XML
        pub_count = Publication.objects.filter(job=event).count()
        self.assertEqual(pub_count, 0, "Malformed XML should not create publications")

    def test_empty_response(self):
        """Test that empty OAI-PMH response (no records) is handled."""
        event = HarvestingEvent.objects.create(
            source=self.source,
            status="in_progress"
        )

        empty_xml_path = BASE_TEST_DIR / 'harvesting' / 'error_cases' / 'empty_response.xml'
        xml_bytes = empty_xml_path.read_bytes()

        # Should not raise exception
        parse_oai_xml_and_save_publications(xml_bytes, event)

        # No publications should be created from empty response
        pub_count = Publication.objects.filter(job=event).count()
        self.assertEqual(pub_count, 0, "Empty response should create zero publications")

    def test_invalid_xml_structure(self):
        """Test that non-OAI-PMH XML structure is handled."""
        event = HarvestingEvent.objects.create(
            source=self.source,
            status="in_progress"
        )

        invalid_xml_path = BASE_TEST_DIR / 'harvesting' / 'error_cases' / 'invalid_xml_structure.xml'
        xml_bytes = invalid_xml_path.read_bytes()

        # Should not raise exception
        parse_oai_xml_and_save_publications(xml_bytes, event)

        # No publications should be created from invalid structure
        pub_count = Publication.objects.filter(job=event).count()
        self.assertEqual(pub_count, 0, "Invalid XML structure should create zero publications")

    def test_missing_required_metadata(self):
        """Test that records with missing required fields are handled."""
        event = HarvestingEvent.objects.create(
            source=self.source,
            status="in_progress"
        )

        missing_metadata_path = BASE_TEST_DIR / 'harvesting' / 'error_cases' / 'missing_metadata.xml'
        xml_bytes = missing_metadata_path.read_bytes()

        # Should not raise exception - may create some publications
        parse_oai_xml_and_save_publications(xml_bytes, event)

        # Check what was created
        pubs = Publication.objects.filter(job=event)

        # At least one record (the one with title) should be created
        self.assertGreaterEqual(pubs.count(), 1, "Should create publications even with minimal metadata")

        # Check that publications were created despite missing fields
        for pub in pubs:
            # Title might be None for some records
            if pub.title:
                self.assertIsInstance(pub.title, str)

    def test_empty_content(self):
        """Test that empty/None content is handled."""
        event = HarvestingEvent.objects.create(
            source=self.source,
            status="in_progress"
        )

        # Test with empty bytes
        parse_oai_xml_and_save_publications(b"", event)
        pub_count = Publication.objects.filter(job=event).count()
        self.assertEqual(pub_count, 0, "Empty content should create zero publications")

        # Test with whitespace only
        parse_oai_xml_and_save_publications(b"   \n\t  ", event)
        pub_count = Publication.objects.filter(job=event).count()
        self.assertEqual(pub_count, 0, "Whitespace-only content should create zero publications")

    @responses.activate
    def test_http_404_error(self):
        """Test that HTTP 404 errors are handled properly."""
        # Mock a 404 response
        responses.add(
            responses.GET,
            'http://example.com/oai-404',
            status=404,
            body='Not Found'
        )

        source = Source.objects.create(
            url_field="http://example.com/oai-404",
            harvest_interval_minutes=60
        )

        # harvest_oai_endpoint should handle the error
        harvest_oai_endpoint(source.id)

        # Check that event was marked as failed
        event = HarvestingEvent.objects.filter(source=source).latest('started_at')
        self.assertEqual(event.status, 'failed', "Event should be marked as failed for 404 error")

    @responses.activate
    def test_http_500_error(self):
        """Test that HTTP 500 errors are handled properly."""
        # Mock a 500 response
        responses.add(
            responses.GET,
            'http://example.com/oai-500',
            status=500,
            body='Internal Server Error'
        )

        source = Source.objects.create(
            url_field="http://example.com/oai-500",
            harvest_interval_minutes=60
        )

        # harvest_oai_endpoint should handle the error
        harvest_oai_endpoint(source.id)

        # Check that event was marked as failed
        event = HarvestingEvent.objects.filter(source=source).latest('started_at')
        self.assertEqual(event.status, 'failed', "Event should be marked as failed for 500 error")

    @responses.activate
    def test_network_timeout(self):
        """Test that network timeouts are handled properly."""
        from requests.exceptions import Timeout

        # Mock a timeout
        responses.add(
            responses.GET,
            'http://example.com/oai-timeout',
            body=Timeout('Connection timeout')
        )

        source = Source.objects.create(
            url_field="http://example.com/oai-timeout",
            harvest_interval_minutes=60
        )

        # harvest_oai_endpoint should handle the timeout
        harvest_oai_endpoint(source.id)

        # Check that event was marked as failed
        event = HarvestingEvent.objects.filter(source=source).latest('started_at')
        self.assertEqual(event.status, 'failed', "Event should be marked as failed for timeout")

    @responses.activate
    def test_invalid_xml_in_http_response(self):
        """Test that invalid XML in HTTP response is handled."""
        # Mock response with invalid XML
        responses.add(
            responses.GET,
            'http://example.com/oai-invalid',
            status=200,
            body='This is not XML at all',
            content_type='text/xml'
        )

        source = Source.objects.create(
            url_field="http://example.com/oai-invalid",
            harvest_interval_minutes=60
        )

        # Should complete but create no publications
        harvest_oai_endpoint(source.id)

        event = HarvestingEvent.objects.filter(source=source).latest('started_at')
        # Should complete (not fail) but create no publications
        self.assertEqual(event.status, 'completed', "Event should complete even with invalid XML")

        pub_count = Publication.objects.filter(job=event).count()
        self.assertEqual(pub_count, 0, "Invalid XML should create zero publications")

    def test_max_records_limit_with_errors(self):
        """Test that max_records works even when some records cause errors."""
        event = HarvestingEvent.objects.create(
            source=self.source,
            status="in_progress"
        )

        # Use the missing metadata file which has 2 records, one problematic
        missing_metadata_path = BASE_TEST_DIR / 'harvesting' / 'error_cases' / 'missing_metadata.xml'
        xml_bytes = missing_metadata_path.read_bytes()

        # Limit to 1 record
        parse_oai_xml_and_save_publications(xml_bytes, event, max_records=1)

        # Should process only 1 record
        pub_count = Publication.objects.filter(job=event).count()
        self.assertLessEqual(pub_count, 1, "Should respect max_records limit even with errors")


class RSSFeedHarvestingTests(TestCase):
    """
    Test cases for RSS/Atom feed harvesting.

    These tests verify that the RSS harvesting system properly handles:
    - RDF/RSS feed parsing
    - Publication extraction from feed entries
    - Duplicate detection
    - DOI and metadata extraction
    """

    def setUp(self):
        """Set up test source for RSS feeds."""
        Publication.objects.all().delete()
        self.source = Source.objects.create(
            url_field="https://www.example.com/feed.rss",
            harvest_interval_minutes=60,
            name="Test RSS Source"
        )

    def test_parse_rss_feed_from_file(self):
        """Test parsing RSS feed from local file."""
        event = HarvestingEvent.objects.create(
            source=self.source,
            status="in_progress"
        )

        rss_feed_path = BASE_TEST_DIR / 'harvesting' / 'rss_feed_sample.xml'
        feed_url = f"file://{rss_feed_path}"

        processed, saved = parse_rss_feed_and_save_publications(feed_url, event)

        # Check counts
        self.assertEqual(processed, 2, "Should process 2 entries")
        self.assertEqual(saved, 2, "Should save 2 publications")

        # Check created publications
        pubs = Publication.objects.filter(job=event)
        self.assertEqual(pubs.count(), 2)

        # Check first publication
        pub1 = pubs.filter(doi='10.1234/test-001').first()
        self.assertIsNotNone(pub1)
        self.assertEqual(pub1.title, 'Test Article One: Data Repository')
        self.assertEqual(pub1.url, 'https://www.example.com/articles/test-article-1')
        self.assertEqual(str(pub1.publicationDate), '2025-10-01')

        # Check second publication
        pub2 = pubs.filter(doi='10.1234/test-002').first()
        self.assertIsNotNone(pub2)
        self.assertEqual(pub2.title, 'Test Article Two: Analysis Methods')

    def test_rss_duplicate_detection_by_doi(self):
        """Test that duplicate detection works by DOI."""
        event = HarvestingEvent.objects.create(
            source=self.source,
            status="in_progress"
        )

        # Create existing publication with same DOI
        Publication.objects.create(
            title="Existing Publication",
            doi="10.1234/test-001",
            source=self.source,
            timeperiod_startdate=[],
            timeperiod_enddate=[]
        )

        rss_feed_path = BASE_TEST_DIR / 'harvesting' / 'rss_feed_sample.xml'
        feed_url = f"file://{rss_feed_path}"

        processed, saved = parse_rss_feed_and_save_publications(feed_url, event)

        # Should process both but only save one (the one without duplicate DOI)
        self.assertEqual(processed, 2)
        self.assertEqual(saved, 1, "Should only save publication without duplicate DOI")

    def test_rss_duplicate_detection_by_url(self):
        """Test that duplicate detection works by URL."""
        event = HarvestingEvent.objects.create(
            source=self.source,
            status="in_progress"
        )

        # Create existing publication with same URL
        Publication.objects.create(
            title="Existing Publication",
            url="https://www.example.com/articles/test-article-1",
            source=self.source,
            timeperiod_startdate=[],
            timeperiod_enddate=[]
        )

        rss_feed_path = BASE_TEST_DIR / 'harvesting' / 'rss_feed_sample.xml'
        feed_url = f"file://{rss_feed_path}"

        processed, saved = parse_rss_feed_and_save_publications(feed_url, event)

        # Should process both but only save one
        self.assertEqual(processed, 2)
        self.assertEqual(saved, 1, "Should only save publication without duplicate URL")

    def test_rss_max_records_limit(self):
        """Test that max_records parameter limits RSS harvesting."""
        event = HarvestingEvent.objects.create(
            source=self.source,
            status="in_progress"
        )

        rss_feed_path = BASE_TEST_DIR / 'harvesting' / 'rss_feed_sample.xml'
        feed_url = f"file://{rss_feed_path}"

        # Limit to 1 record
        processed, saved = parse_rss_feed_and_save_publications(feed_url, event, max_records=1)

        self.assertEqual(processed, 1, "Should only process 1 entry")
        self.assertEqual(saved, 1, "Should only save 1 publication")

        pubs = Publication.objects.filter(job=event)
        self.assertEqual(pubs.count(), 1)

    def test_harvest_rss_endpoint_from_file(self):
        """Test complete RSS harvesting workflow from file."""
        rss_feed_path = BASE_TEST_DIR / 'harvesting' / 'rss_feed_sample.xml'

        # Update source to use file:// URL
        self.source.url_field = f"file://{rss_feed_path}"
        self.source.save()

        # Harvest
        harvest_rss_endpoint(self.source.id, max_records=10)

        # Check event status
        event = HarvestingEvent.objects.filter(source=self.source).latest('started_at')
        self.assertEqual(event.status, 'completed')

        # Check publications
        pubs = Publication.objects.filter(job=event)
        self.assertEqual(pubs.count(), 2, "Should create 2 publications from RSS feed")

    def test_harvest_rss_endpoint_invalid_file(self):
        """Test RSS harvesting handles invalid file paths."""
        # Update source to use non-existent file
        self.source.url_field = "file:///tmp/nonexistent_rss_feed.xml"
        self.source.save()

        # Harvest should handle error gracefully
        harvest_rss_endpoint(self.source.id)

        # Check event was marked as completed (feedparser returns empty feed for invalid URLs)
        event = HarvestingEvent.objects.filter(source=self.source).latest('started_at')
        # Event completes but creates no publications
        self.assertEqual(event.status, 'completed')

        # No publications should be created
        pubs = Publication.objects.filter(job=event)
        self.assertEqual(pubs.count(), 0)

    def test_rss_invalid_feed_url(self):
        """Test handling of invalid RSS feed URL."""
        event = HarvestingEvent.objects.create(
            source=self.source,
            status="in_progress"
        )

        # Try to parse non-existent file
        feed_url = "file:///tmp/nonexistent_feed.xml"

        processed, saved = parse_rss_feed_and_save_publications(feed_url, event)

        # Should handle gracefully and return zero
        self.assertEqual(processed, 0)
        self.assertEqual(saved, 0)

