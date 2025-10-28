"""Tests for geometry contribution and publication workflow."""
import json
from django.test import TestCase, Client
from django.contrib.gis.geos import Point, GeometryCollection
from django.utils import timezone
from works.models import Work, Source
from django.contrib.auth import get_user_model

User = get_user_model()


class GeometryContributionTests(TestCase):
    """Test geometry contribution API endpoint."""

    def setUp(self):
        """Set up test data."""
        self.client = Client()

        # Create users
        self.regular_user = User.objects.create_user(
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

        # Create source
        self.source = Source.objects.create(
            name="Test Journal",
            url_field="https://example.com/oai",
            homepage_url="https://example.com/journal"
        )

        # Create harvested publication without geometry
        self.pub_harvested = Work.objects.create(
            title="Harvested Publication Without Geometry",
            abstract="This needs geolocation",
            url="https://example.com/article1",
            doi="10.1234/harvested",
            status="h",  # Harvested
            publicationDate=timezone.now().date(),
            geometry=GeometryCollection(),  # Empty geometry
            source=self.source,
            provenance="Harvested via OAI-PMH on 2025-01-01."
        )

        # Create harvested publication with existing geometry
        self.pub_with_geometry = Work.objects.create(
            title="Publication With Geometry",
            abstract="This already has location",
            url="https://example.com/article2",
            doi="10.1234/withgeo",
            status="h",
            publicationDate=timezone.now().date(),
            geometry=GeometryCollection(Point(12.4924, 41.8902)),
            source=self.source
        )

        # Create published publication
        self.pub_published = Work.objects.create(
            title="Published Publication",
            abstract="This is published",
            url="https://example.com/article3",
            doi="10.1234/published",
            status="p",  # Published
            publicationDate=timezone.now().date(),
            geometry=GeometryCollection(),
            source=self.source
        )

        # Sample geometry for contributions
        self.test_geometry = {
            "type": "GeometryCollection",
            "geometries": [
                {
                    "type": "Point",
                    "coordinates": [13.4050, 52.5200]
                }
            ]
        }

    def test_contribute_geometry_requires_authentication(self):
        """Test that contribution requires authentication."""
        url = f'/work/{self.pub_harvested.doi}/contribute-geometry/'
        response = self.client.post(
            url,
            data=json.dumps({'geometry': self.test_geometry}),
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 401)
        data = response.json()
        self.assertEqual(data['error'], 'Authentication required')

    def test_contribute_geometry_success(self):
        """Test successful geometry contribution."""
        self.client.login(username='contributor@example.com', password='testpass123')

        url = f'/work/{self.pub_harvested.doi}/contribute-geometry/'
        response = self.client.post(
            url,
            data=json.dumps({'geometry': self.test_geometry}),
            content_type='application/json'
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['success'])
        self.assertIn('Thank you for your contribution', data['message'])

        # Verify database changes
        self.pub_harvested.refresh_from_db()
        self.assertEqual(self.pub_harvested.status, 'c')  # Contributed
        self.assertFalse(self.pub_harvested.geometry.empty)

        # Verify provenance
        self.assertIn('contributor@example.com', self.pub_harvested.provenance)
        self.assertIn('Contribution by user', self.pub_harvested.provenance)
        self.assertIn('Status changed from Harvested to Contributed', self.pub_harvested.provenance)

    def test_contribute_geometry_publication_not_found(self):
        """Test contribution to non-existent publication."""
        self.client.login(username='contributor@example.com', password='testpass123')

        url = '/work/10.1234/nonexistent/contribute-geometry/'
        response = self.client.post(
            url,
            data=json.dumps({'geometry': self.test_geometry}),
            content_type='application/json'
        )

        self.assertEqual(response.status_code, 404)
        data = response.json()
        self.assertEqual(data['error'], 'Work not found')

    def test_contribute_geometry_wrong_status(self):
        """Test that only harvested publications can receive contributions."""
        self.client.login(username='contributor@example.com', password='testpass123')

        url = f'/work/{self.pub_published.doi}/contribute-geometry/'
        response = self.client.post(
            url,
            data=json.dumps({'geometry': self.test_geometry}),
            content_type='application/json'
        )

        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertEqual(data['error'], 'Can only contribute to harvested publications')

    def test_contribute_geometry_already_has_geometry(self):
        """Test that publications with geometry cannot receive new contributions."""
        self.client.login(username='contributor@example.com', password='testpass123')

        url = f'/work/{self.pub_with_geometry.doi}/contribute-geometry/'
        response = self.client.post(
            url,
            data=json.dumps({'geometry': self.test_geometry}),
            content_type='application/json'
        )

        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertEqual(data['error'], 'Work already has geometry')

    def test_contribute_geometry_no_geometry_provided(self):
        """Test error when no geometry is provided."""
        self.client.login(username='contributor@example.com', password='testpass123')

        url = f'/work/{self.pub_harvested.doi}/contribute-geometry/'
        response = self.client.post(
            url,
            data=json.dumps({}),
            content_type='application/json'
        )

        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertEqual(data['error'], 'No geometry or temporal extent provided')

    def test_contribute_geometry_invalid_json(self):
        """Test error when invalid JSON is sent."""
        self.client.login(username='contributor@example.com', password='testpass123')

        url = f'/work/{self.pub_harvested.doi}/contribute-geometry/'
        response = self.client.post(
            url,
            data='invalid json',
            content_type='application/json'
        )

        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertEqual(data['error'], 'Invalid JSON')

    def test_contribute_geometry_polygon(self):
        """Test contribution with polygon geometry."""
        self.client.login(username='contributor@example.com', password='testpass123')

        polygon_geometry = {
            "type": "GeometryCollection",
            "geometries": [
                {
                    "type": "Polygon",
                    "coordinates": [[
                        [13.0, 52.0],
                        [14.0, 52.0],
                        [14.0, 53.0],
                        [13.0, 53.0],
                        [13.0, 52.0]
                    ]]
                }
            ]
        }

        url = f'/work/{self.pub_harvested.doi}/contribute-geometry/'
        response = self.client.post(
            url,
            data=json.dumps({'geometry': polygon_geometry}),
            content_type='application/json'
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['success'])

        self.pub_harvested.refresh_from_db()
        self.assertEqual(self.pub_harvested.status, 'c')
        self.assertFalse(self.pub_harvested.geometry.empty)


class PublishWorkTests(TestCase):
    """Test publish work API endpoint."""

    def setUp(self):
        """Set up test data."""
        self.client = Client()

        # Create users
        self.regular_user = User.objects.create_user(
            username='user@example.com',
            email='user@example.com',
            password='testpass123'
        )

        self.admin_user = User.objects.create_user(
            username='admin@example.com',
            email='admin@example.com',
            password='adminpass123',
            is_staff=True,
            is_superuser=True
        )

        # Create source
        self.source = Source.objects.create(
            name="Test Journal",
            url_field="https://example.com/oai"
        )

        # Create contributed publication
        self.pub_contributed = Work.objects.create(
            title="Contributed Publication",
            abstract="User contributed location",
            url="https://example.com/article1",
            doi="10.1234/contributed",
            status="c",  # Contributed
            publicationDate=timezone.now().date(),
            geometry=GeometryCollection(Point(13.4050, 52.5200)),
            source=self.source,
            provenance="Geometry contributed by user@example.com on 2025-01-01."
        )

        # Create harvested publication
        self.pub_harvested = Work.objects.create(
            title="Harvested Publication",
            abstract="Not yet contributed",
            url="https://example.com/article2",
            doi="10.1234/harvested",
            status="h",  # Harvested
            publicationDate=timezone.now().date(),
            geometry=GeometryCollection(),
            source=self.source
        )

    def test_publish_requires_admin(self):
        """Test that publishing requires admin privileges."""
        self.client.login(username='user@example.com', password='testpass123')

        url = f'/work/{self.pub_contributed.doi}/publish/'
        response = self.client.post(url, content_type='application/json')

        # staff_member_required redirects non-staff users
        self.assertEqual(response.status_code, 302)

    def test_publish_success(self):
        """Test successful publication."""
        self.client.login(username='admin@example.com', password='adminpass123')

        url = f'/work/{self.pub_contributed.doi}/publish/'
        response = self.client.post(url, content_type='application/json')

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['success'])
        self.assertIn('Work is now public', data['message'])

        # Verify database changes
        self.pub_contributed.refresh_from_db()
        self.assertEqual(self.pub_contributed.status, 'p')  # Published

        # Verify provenance
        self.assertIn('admin@example.com', self.pub_contributed.provenance)
        self.assertIn('Published by admin', self.pub_contributed.provenance)
        self.assertIn('Status changed from Contributed to Published', self.pub_contributed.provenance)

    def test_publish_publication_not_found(self):
        """Test publishing non-existent publication."""
        self.client.login(username='admin@example.com', password='adminpass123')

        url = '/work/10.1234/nonexistent/publish/'
        response = self.client.post(url, content_type='application/json')

        self.assertEqual(response.status_code, 404)
        data = response.json()
        self.assertEqual(data['error'], 'Work not found')

    def test_publish_wrong_status(self):
        """Test that harvested publications without geometry cannot be published."""
        self.client.login(username='admin@example.com', password='adminpass123')

        url = f'/work/{self.pub_harvested.doi}/publish/'
        response = self.client.post(url, content_type='application/json')

        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertEqual(data['error'], 'Cannot publish harvested work without spatial or temporal extent')

    def test_publish_harvested_with_geometry(self):
        """Test that harvested publications with geometry can be published."""
        # Create a harvested publication with geometry
        from django.contrib.gis.geos import Point, GeometryCollection
        pub_harvested_with_geo = Work.objects.create(
            title='Harvested with Geometry',
            status='h',
            doi='10.1234/harvested-geo',
            geometry=GeometryCollection(Point(13.405, 52.52)),
            source=self.source
        )

        self.client.login(username='admin@example.com', password='adminpass123')

        url = f'/work/{pub_harvested_with_geo.doi}/publish/'
        response = self.client.post(url, content_type='application/json')

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['success'])

        # Verify database changes
        pub_harvested_with_geo.refresh_from_db()
        self.assertEqual(pub_harvested_with_geo.status, 'p')  # Published
        self.assertIn('Harvested', pub_harvested_with_geo.provenance)
        self.assertIn('Published by admin', pub_harvested_with_geo.provenance)


class WorkflowIntegrationTests(TestCase):
    """Test the complete contribution and publication workflow."""

    def setUp(self):
        """Set up test data."""
        self.client = Client()

        # Create users
        self.contributor = User.objects.create_user(
            username='contributor@example.com',
            email='contributor@example.com',
            password='testpass123'
        )

        self.admin = User.objects.create_user(
            username='admin@example.com',
            email='admin@example.com',
            password='adminpass123',
            is_staff=True,
            is_superuser=True
        )

        # Create source
        self.source = Source.objects.create(
            name="Test Journal",
            url_field="https://example.com/oai"
        )

        # Create harvested publication
        self.work = Work.objects.create(
            title="Test Publication",
            abstract="Test abstract",
            url="https://example.com/article",
            doi="10.1234/test",
            status="h",  # Harvested
            publicationDate=timezone.now().date(),
            geometry=GeometryCollection(),
            source=self.source,
            provenance="Harvested via OAI-PMH."
        )

        self.test_geometry = {
            "type": "GeometryCollection",
            "geometries": [
                {
                    "type": "Point",
                    "coordinates": [13.4050, 52.5200]
                }
            ]
        }

    def test_complete_workflow(self):
        """Test complete workflow: harvest -> contribute -> publish."""
        # Step 1: Verify initial state
        self.assertEqual(self.work.status, 'h')
        self.assertTrue(self.work.geometry.empty)

        # Step 2: User contributes geometry
        self.client.login(username='contributor@example.com', password='testpass123')
        contribute_url = f'/work/{self.work.doi}/contribute-geometry/'
        response = self.client.post(
            contribute_url,
            data=json.dumps({'geometry': self.test_geometry}),
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 200)

        # Verify contribution
        self.work.refresh_from_db()
        self.assertEqual(self.work.status, 'c')  # Contributed
        self.assertFalse(self.work.geometry.empty)
        self.assertIn('contributor@example.com', self.work.provenance)

        # Step 3: Admin publishes the contribution
        self.client.login(username='admin@example.com', password='adminpass123')
        publish_url = f'/work/{self.work.doi}/publish/'
        response = self.client.post(publish_url, content_type='application/json')
        self.assertEqual(response.status_code, 200)

        # Verify publication
        self.work.refresh_from_db()
        self.assertEqual(self.work.status, 'p')  # Published
        self.assertIn('admin@example.com', self.work.provenance)

        # Verify complete provenance trail
        provenance = self.work.provenance
        self.assertIn('Harvested via OAI-PMH', provenance)
        self.assertIn('Contribution by user contributor@example.com', provenance)
        self.assertIn('Status changed from Harvested to Contributed', provenance)
        self.assertIn('Published by admin admin@example.com', provenance)
        self.assertIn('Status changed from Contributed to Published', provenance)


class UnpublishWorkTests(TestCase):
    """Test unpublish work API endpoint."""

    def setUp(self):
        """Set up test data."""
        self.client = Client()

        # Create source
        self.source = Source.objects.create(
            name='Test Source',
            is_oa=True,
            is_preprint=False
        )

        # Create users
        self.regular_user = User.objects.create_user(
            username='user@example.com',
            email='user@example.com',
            password='testpass123'
        )

        self.admin_user = User.objects.create_user(
            username='admin@example.com',
            email='admin@example.com',
            password='adminpass123',
            is_staff=True,
            is_superuser=True
        )

        # Create published publication
        self.pub_published = Work.objects.create(
            title='Published Publication',
            status='p',  # Published
            doi='10.1234/published',
            geometry=GeometryCollection(Point(13.405, 52.52)),
            source=self.source
        )

        # Create contributed publication (not yet published)
        self.pub_contributed = Work.objects.create(
            title='Contributed Publication',
            status='c',  # Contributed
            doi='10.1234/contributed',
            geometry=GeometryCollection(Point(13.405, 52.52)),
            source=self.source
        )

    def test_unpublish_requires_admin(self):
        """Test that unpublishing requires admin privileges."""
        self.client.login(username='user@example.com', password='testpass123')

        url = f'/work/{self.pub_published.doi}/unpublish/'
        response = self.client.post(url, content_type='application/json')

        # staff_member_required redirects non-staff users
        self.assertEqual(response.status_code, 302)

    def test_unpublish_success(self):
        """Test successful unpublishing."""
        self.client.login(username='admin@example.com', password='adminpass123')

        url = f'/work/{self.pub_published.doi}/unpublish/'
        response = self.client.post(url, content_type='application/json')

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['success'])
        self.assertIn('unpublished', data['message'].lower())

        # Verify database changes
        self.pub_published.refresh_from_db()
        self.assertEqual(self.pub_published.status, 'd')  # Draft

        # Verify provenance
        self.assertIn('admin@example.com', self.pub_published.provenance)
        self.assertIn('Unpublished by admin', self.pub_published.provenance)
        self.assertIn('Status changed from Published to Draft', self.pub_published.provenance)

    def test_unpublish_wrong_status(self):
        """Test that only published publications can be unpublished."""
        self.client.login(username='admin@example.com', password='adminpass123')

        url = f'/work/{self.pub_contributed.doi}/unpublish/'
        response = self.client.post(url, content_type='application/json')

        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertEqual(data['error'], 'Can only unpublish published works')

    def test_unpublish_publication_not_found(self):
        """Test unpublishing non-existent publication."""
        self.client.login(username='admin@example.com', password='adminpass123')

        url = '/work/10.1234/nonexistent/unpublish/'
        response = self.client.post(url, content_type='application/json')

        self.assertEqual(response.status_code, 404)
        data = response.json()
        self.assertEqual(data['error'], 'Work not found')
