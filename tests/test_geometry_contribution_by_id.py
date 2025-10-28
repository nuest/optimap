"""Tests for ID-based geometry contribution (publications without DOI)."""
import json
from django.test import TestCase, Client
from django.contrib.gis.geos import Point, GeometryCollection
from django.utils import timezone
from works.models import Work, Source
from django.contrib.auth import get_user_model

User = get_user_model()


class GeometryContributionByIdTests(TestCase):
    """Test ID-based geometry contribution API endpoint for publications without DOI."""

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

        # Create test publication WITHOUT DOI (harvested, no geometry)
        self.pub_without_doi = Work.objects.create(
            title='Publication Without DOI',
            status='h',  # Harvested
            doi=None,  # No DOI
            url='http://repository.example.org/id/12345',
            geometry=GeometryCollection(),
            source=self.source
        )

        # Create test publication with contributed geometry but no DOI
        self.pub_contributed_no_doi = Work.objects.create(
            title='Contributed Publication Without DOI',
            status='c',  # Contributed
            doi=None,
            url='http://repository.example.org/id/67890',
            geometry=GeometryCollection(Point(13.405, 52.52)),
            source=self.source
        )

        self.test_geometry = {
            "type": "GeometryCollection",
            "geometries": [
                {
                    "type": "Point",
                    "coordinates": [13.405, 52.52]
                }
            ]
        }

    def test_contribute_geometry_by_id_success(self):
        """Test successful geometry contribution using publication ID."""
        self.client.login(username='contributor@example.com', password='testpass123')

        url = f'/work/{self.pub_without_doi.id}/contribute-geometry/'
        response = self.client.post(
            url,
            data=json.dumps({'geometry': self.test_geometry}),
            content_type='application/json'
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['success'])

        # Verify database changes
        self.pub_without_doi.refresh_from_db()
        self.assertEqual(self.pub_without_doi.status, 'c')  # Contributed
        self.assertFalse(self.pub_without_doi.geometry.empty)

        # Verify provenance
        self.assertIn('contributor@example.com', self.pub_without_doi.provenance)
        self.assertIn('Contribution by user', self.pub_without_doi.provenance)

    def test_contribute_geometry_by_id_requires_authentication(self):
        """Test that contribution by ID requires authentication."""
        url = f'/work/{self.pub_without_doi.id}/contribute-geometry/'
        response = self.client.post(
            url,
            data=json.dumps({'geometry': self.test_geometry}),
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 401)

    def test_publish_work_by_id_success(self):
        """Test successful publishing using publication ID."""
        self.client.login(username='admin@example.com', password='adminpass123')

        url = f'/work/{self.pub_contributed_no_doi.id}/publish/'
        response = self.client.post(url, content_type='application/json')

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['success'])

        # Verify database changes
        self.pub_contributed_no_doi.refresh_from_db()
        self.assertEqual(self.pub_contributed_no_doi.status, 'p')  # Published

        # Verify provenance
        self.assertIn('admin@example.com', self.pub_contributed_no_doi.provenance)
        self.assertIn('Published by admin', self.pub_contributed_no_doi.provenance)

    def test_work_landing_by_id_accessible(self):
        """Test that publication landing page is accessible by ID."""
        # Make publication published so it's accessible
        self.pub_without_doi.status = 'p'
        self.pub_without_doi.save()

        url = f'/work/{self.pub_without_doi.id}/'
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.pub_without_doi.title)
        # Check that ID URLs flag is set in JavaScript
        self.assertContains(response, 'const useIdUrls = true')
        # Check that publication ID is available in JavaScript
        self.assertContains(response, f'const pubId = {self.pub_without_doi.id}')


class MixedDOIAndIDTests(TestCase):
    """Test that both DOI-based and ID-based URLs work correctly."""

    def setUp(self):
        self.source = Source.objects.create(
            name='Test Source',
            is_oa=True,
            is_preprint=False
        )

        self.user = User.objects.create_user(
            username='user@example.com',
            email='user@example.com',
            password='testpass123'
        )

        # Publication with DOI
        self.pub_with_doi = Work.objects.create(
            title='Publication With DOI',
            status='h',
            doi='10.5555/test123',
            geometry=GeometryCollection(),
            source=self.source
        )

        # Publication without DOI
        self.pub_without_doi = Work.objects.create(
            title='Publication Without DOI',
            status='h',
            doi=None,
            url='http://example.org/123',
            geometry=GeometryCollection(),
            source=self.source
        )

        self.test_geometry = {
            "type": "GeometryCollection",
            "geometries": [{"type": "Point", "coordinates": [13.405, 52.52]}]
        }

    def test_both_url_types_work(self):
        """Test that both DOI-based and ID-based contribution URLs work."""
        self.client.login(username='user@example.com', password='testpass123')

        # Test DOI-based URL
        doi_url = f'/work/{self.pub_with_doi.doi}/contribute-geometry/'
        response1 = self.client.post(
            doi_url,
            data=json.dumps({'geometry': self.test_geometry}),
            content_type='application/json'
        )
        self.assertEqual(response1.status_code, 200)

        # Test ID-based URL
        id_url = f'/work/{self.pub_without_doi.id}/contribute-geometry/'
        response2 = self.client.post(
            id_url,
            data=json.dumps({'geometry': self.test_geometry}),
            content_type='application/json'
        )
        self.assertEqual(response2.status_code, 200)

        # Verify both publications were updated
        self.pub_with_doi.refresh_from_db()
        self.pub_without_doi.refresh_from_db()
        self.assertEqual(self.pub_with_doi.status, 'c')
        self.assertEqual(self.pub_without_doi.status, 'c')
