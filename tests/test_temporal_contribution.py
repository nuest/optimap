"""Tests for temporal extent contribution functionality."""
import json
from django.test import TestCase, Client
from django.contrib.gis.geos import Point, GeometryCollection
from works.models import Work, Source
from django.contrib.auth import get_user_model

User = get_user_model()


class TemporalExtentContributionTests(TestCase):
    """Test temporal extent contribution API endpoint."""

    def setUp(self):
        # Create source
        self.source = Source.objects.create(
            name='Test Source',
            is_oa=True,
            is_preprint=False
        )

        # Create users
        self.contributor = User.objects.create_user(
            username='contributor@example.com',
            email='contributor@example.com',
            password='testpass123'
        )

        self.admin_user = User.objects.create_user(
            username='admin@example.com',
            email='admin@example.com',
            password='adminpass123',
            is_staff=True,
            is_superuser=True
        )

        # Create test publication WITHOUT temporal extent
        self.pub_without_temporal = Work.objects.create(
            title='Publication Without Temporal Extent',
            status='h',  # Harvested
            doi='10.1234/no-temporal',
            geometry=GeometryCollection(),
            source=self.source,
            timeperiod_startdate=None,
            timeperiod_enddate=None
        )

    def test_contribute_temporal_extent_success(self):
        """Test successful temporal extent contribution."""
        self.client.login(username='contributor@example.com', password='testpass123')

        url = f'/work/{self.pub_without_temporal.doi}/contribute-geometry/'
        temporal_data = {
            'start_date': '2010',
            'end_date': '2020'
        }
        response = self.client.post(
            url,
            data=json.dumps({'temporal_extent': temporal_data}),
            content_type='application/json'
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['success'])

        # Verify database changes
        self.pub_without_temporal.refresh_from_db()
        self.assertEqual(self.pub_without_temporal.status, 'c')  # Contributed
        self.assertEqual(self.pub_without_temporal.timeperiod_startdate, ['2010'])
        self.assertEqual(self.pub_without_temporal.timeperiod_enddate, ['2020'])

        # Verify provenance
        self.assertIn('contributor@example.com', self.pub_without_temporal.provenance)
        self.assertIn('Set start date to 2010', self.pub_without_temporal.provenance)
        self.assertIn('Set end date to 2020', self.pub_without_temporal.provenance)

    def test_contribute_only_start_date(self):
        """Test contributing only start date."""
        self.client.login(username='contributor@example.com', password='testpass123')

        url = f'/work/{self.pub_without_temporal.doi}/contribute-geometry/'
        temporal_data = {'start_date': '2015-06'}
        response = self.client.post(
            url,
            data=json.dumps({'temporal_extent': temporal_data}),
            content_type='application/json'
        )

        self.assertEqual(response.status_code, 200)
        self.pub_without_temporal.refresh_from_db()
        self.assertEqual(self.pub_without_temporal.timeperiod_startdate, ['2015-06'])
        self.assertIsNone(self.pub_without_temporal.timeperiod_enddate)

    def test_contribute_only_end_date(self):
        """Test contributing only end date."""
        self.client.login(username='contributor@example.com', password='testpass123')

        url = f'/work/{self.pub_without_temporal.doi}/contribute-geometry/'
        temporal_data = {'end_date': '2020-12-31'}
        response = self.client.post(
            url,
            data=json.dumps({'temporal_extent': temporal_data}),
            content_type='application/json'
        )

        self.assertEqual(response.status_code, 200)
        self.pub_without_temporal.refresh_from_db()
        self.assertIsNone(self.pub_without_temporal.timeperiod_startdate)
        self.assertEqual(self.pub_without_temporal.timeperiod_enddate, ['2020-12-31'])

    def test_contribute_both_geometry_and_temporal(self):
        """Test contributing both geometry and temporal extent in one request."""
        self.client.login(username='contributor@example.com', password='testpass123')

        url = f'/work/{self.pub_without_temporal.doi}/contribute-geometry/'
        data = {
            'geometry': {
                'type': 'GeometryCollection',
                'geometries': [
                    {'type': 'Point', 'coordinates': [13.405, 52.52]}
                ]
            },
            'temporal_extent': {
                'start_date': '2010',
                'end_date': '2020'
            }
        }
        response = self.client.post(
            url,
            data=json.dumps(data),
            content_type='application/json'
        )

        self.assertEqual(response.status_code, 200)
        self.pub_without_temporal.refresh_from_db()

        # Verify both geometry and temporal extent were set
        self.assertFalse(self.pub_without_temporal.geometry.empty)
        self.assertEqual(self.pub_without_temporal.timeperiod_startdate, ['2010'])
        self.assertEqual(self.pub_without_temporal.timeperiod_enddate, ['2020'])
        self.assertEqual(self.pub_without_temporal.status, 'c')

    def test_contribute_temporal_requires_authentication(self):
        """Test that temporal contribution requires authentication."""
        url = f'/work/{self.pub_without_temporal.doi}/contribute-geometry/'
        temporal_data = {'start_date': '2010'}
        response = self.client.post(
            url,
            data=json.dumps({'temporal_extent': temporal_data}),
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 401)

    def test_publish_work_with_only_temporal_extent(self):
        """Test that works with only temporal extent (no geometry) can be published."""
        # Set up publication with only temporal extent
        pub = Work.objects.create(
            title='Publication with Only Temporal',
            status='h',
            doi='10.1234/only-temporal',
            geometry=GeometryCollection(),  # Empty
            source=self.source,
            timeperiod_startdate=['2010'],
            timeperiod_enddate=['2020']
        )

        self.client.login(username='admin@example.com', password='adminpass123')
        url = f'/work/{pub.doi}/publish/'
        response = self.client.post(url, content_type='application/json')

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['success'])

        pub.refresh_from_db()
        self.assertEqual(pub.status, 'p')  # Published

    def test_publish_work_with_only_geometry(self):
        """Test that works with only geometry (no temporal extent) can be published."""
        # Set up publication with only geometry
        pub = Work.objects.create(
            title='Publication with Only Geometry',
            status='h',
            doi='10.1234/only-geometry',
            geometry=GeometryCollection(Point(13.405, 52.52)),
            source=self.source,
            timeperiod_startdate=None,
            timeperiod_enddate=None
        )

        self.client.login(username='admin@example.com', password='adminpass123')
        url = f'/work/{pub.doi}/publish/'
        response = self.client.post(url, content_type='application/json')

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['success'])

        pub.refresh_from_db()
        self.assertEqual(pub.status, 'p')  # Published

    def test_cannot_publish_without_any_extent(self):
        """Test that harvested works without any extent cannot be published."""
        # Set up publication with neither geometry nor temporal extent
        pub = Work.objects.create(
            title='Publication with No Extent',
            status='h',
            doi='10.1234/no-extent',
            geometry=GeometryCollection(),  # Empty
            source=self.source,
            timeperiod_startdate=None,
            timeperiod_enddate=None
        )

        self.client.login(username='admin@example.com', password='adminpass123')
        url = f'/work/{pub.doi}/publish/'
        response = self.client.post(url, content_type='application/json')

        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertIn('spatial or temporal extent', data['error'])

        pub.refresh_from_db()
        self.assertEqual(pub.status, 'h')  # Still harvested


class ContributePageFilterTests(TestCase):
    """Test that contribute page shows publications missing either spatial or temporal extent."""

    def setUp(self):
        self.source = Source.objects.create(
            name='Test Source',
            is_oa=True,
            is_preprint=False
        )

    def test_contribute_page_shows_missing_geometry(self):
        """Contribute page should show publications missing geometry."""
        pub = Work.objects.create(
            title='Missing Geometry',
            status='h',
            doi='10.1234/missing-geo',
            geometry=GeometryCollection(),  # Empty
            source=self.source,
            timeperiod_startdate=['2010'],
            timeperiod_enddate=['2020']
        )

        response = self.client.get('/contribute/')
        self.assertEqual(response.status_code, 200)
        self.assertIn(pub, response.context['works'])

    def test_contribute_page_shows_missing_temporal(self):
        """Contribute page should show publications missing temporal extent."""
        pub = Work.objects.create(
            title='Missing Temporal',
            status='h',
            doi='10.1234/missing-temporal',
            geometry=GeometryCollection(Point(13.405, 52.52)),
            source=self.source,
            timeperiod_startdate=None,
            timeperiod_enddate=None
        )

        response = self.client.get('/contribute/')
        self.assertEqual(response.status_code, 200)
        self.assertIn(pub, response.context['works'])

    def test_contribute_page_shows_missing_both(self):
        """Contribute page should show publications missing both extents."""
        pub = Work.objects.create(
            title='Missing Both',
            status='h',
            doi='10.1234/missing-both',
            geometry=GeometryCollection(),  # Empty
            source=self.source,
            timeperiod_startdate=None,
            timeperiod_enddate=None
        )

        response = self.client.get('/contribute/')
        self.assertEqual(response.status_code, 200)
        self.assertIn(pub, response.context['works'])

    def test_contribute_page_hides_complete_publications(self):
        """Contribute page should not show publications with both extents."""
        pub = Work.objects.create(
            title='Complete Publication',
            status='h',
            doi='10.1234/complete',
            geometry=GeometryCollection(Point(13.405, 52.52)),
            source=self.source,
            timeperiod_startdate=['2010'],
            timeperiod_enddate=['2020']
        )

        response = self.client.get('/contribute/')
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(pub, response.context['works'])
