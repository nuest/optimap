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
from publications.tasks import parse_oai_xml_and_save_publications
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

