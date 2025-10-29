from django.test import TestCase, Client
from django.urls import reverse
from works.models import Work, Source
from django.contrib.gis.geos import Point, GeometryCollection
from django.utils.timezone import now
from datetime import timedelta
from django.contrib.auth import get_user_model

User = get_user_model()


class WorkLandingPageTest(TestCase):
    """Tests for the work landing page view and its links."""

    def setUp(self):
        self.client = Client()

        # Create a test source
        self.source = Source.objects.create(
            name="Test Journal",
            url_field="https://example.com/oai",
            homepage_url="https://example.com/journal",
            issn_l="1234-5678"
        )

        # Create a test publication with DOI
        self.pub_with_doi = Work.objects.create(
            title="Test Publication with DOI",
            abstract="Test abstract for publication with DOI",
            url="https://example.com/pub1",
            status="p",
            publicationDate=now() - timedelta(days=30),
            doi="10.1234/test-doi",
            geometry=GeometryCollection(Point(12.4924, 41.8902)),
            source=self.source
        )

        # Create a test publication without source homepage_url
        self.source_no_homepage = Source.objects.create(
            name="Test Journal No Homepage",
            url_field="https://example.com/oai2",
            homepage_url=None,
            issn_l="8765-4321"
        )

        self.pub_no_homepage = Work.objects.create(
            title="Test Publication No Homepage",
            abstract="Test abstract",
            url="https://example.com/pub2",
            status="p",
            publicationDate=now() - timedelta(days=20),
            doi="10.5678/another-doi",
            geometry=GeometryCollection(Point(13.4050, 52.5200)),
            source=self.source_no_homepage
        )

    def test_work_landing_page_loads(self):
        """Test that the work landing page loads successfully."""
        response = self.client.get(f"/work/{self.pub_with_doi.doi}/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.pub_with_doi.title)

    def test_work_landing_page_with_geometry(self):
        """Test that work landing page properly handles geometry (regression test for json import)."""
        # This test catches: NameError: name 'json' is not defined
        # by ensuring the view can process geometry.geojson and create feature_json
        response = self.client.get(f"/work/{self.pub_with_doi.doi}/")
        self.assertEqual(response.status_code, 200)

        # Verify feature_json is in context (requires json import to create)
        self.assertIn('feature_json', response.context)
        feature_json_str = response.context['feature_json']

        # Verify it's valid JSON string that can be parsed
        self.assertIsInstance(feature_json_str, str)

        # Parse it to verify it's valid GeoJSON (this also tests json usage)
        import json
        feature_data = json.loads(feature_json_str)
        self.assertEqual(feature_data['type'], 'Feature')
        self.assertIn('geometry', feature_data)
        self.assertIn('properties', feature_data)

    def test_doi_link_is_correct(self):
        """Test that the DOI link points to the correct DOI resolver URL."""
        response = self.client.get(f"/work/{self.pub_with_doi.doi}/")
        self.assertEqual(response.status_code, 200)

        # Check that the DOI link is present and correct
        expected_doi_url = f'https://doi.org/{self.pub_with_doi.doi}'
        self.assertContains(response, expected_doi_url)
        self.assertContains(response, f'<a href="{expected_doi_url}"')

    def test_source_link_with_homepage_url(self):
        """Test that the source link points to the homepage_url when available."""
        response = self.client.get(f"/work/{self.pub_with_doi.doi}/")
        self.assertEqual(response.status_code, 200)

        # Check that the source homepage link is present
        self.assertContains(response, self.source.homepage_url)
        self.assertContains(response, f'<a href="{self.source.homepage_url}"')
        self.assertContains(response, self.source.name)

    def test_source_without_homepage_url(self):
        """Test that source name is displayed as text when homepage_url is not available."""
        response = self.client.get(f"/work/{self.pub_no_homepage.doi}/")
        self.assertEqual(response.status_code, 200)

        # Check that the source name is present but not as a link
        self.assertContains(response, self.source_no_homepage.name)
        # Should not have a link to the source since homepage_url is None
        self.assertNotContains(response, f'<a href="None"')

    def test_raw_json_api_link_is_correct(self):
        """Test that the raw JSON API link is correct and uses the publication ID."""
        response = self.client.get(f"/work/{self.pub_with_doi.doi}/")
        self.assertEqual(response.status_code, 200)

        # Check that the API link is present
        expected_api_url = f'/api/v1/works/{self.pub_with_doi.id}/'
        self.assertContains(response, expected_api_url)
        self.assertContains(response, 'View raw JSON from API')

    def test_raw_json_api_returns_valid_json(self):
        """Test that the raw JSON API endpoint returns valid JSON data."""
        # First get the work landing page to ensure publication exists
        response = self.client.get(f"/work/{self.pub_with_doi.doi}/")
        self.assertEqual(response.status_code, 200)

        # Now test the API endpoint
        api_response = self.client.get(f'/api/v1/works/{self.pub_with_doi.id}/')
        self.assertEqual(api_response.status_code, 200)
        self.assertIn('application/json', api_response['Content-Type'])

        # Check that the JSON contains expected fields
        data = api_response.json()

        # GeoJSON Feature format has properties
        if 'properties' in data:
            # GeoFeatureModelSerializer returns GeoJSON Feature
            self.assertEqual(data['type'], 'Feature')
            self.assertEqual(data['properties']['title'], self.pub_with_doi.title)
            self.assertEqual(data['properties']['doi'], self.pub_with_doi.doi)
            self.assertEqual(data['properties']['abstract'], self.pub_with_doi.abstract)
        else:
            # Regular serializer format
            self.assertEqual(data['title'], self.pub_with_doi.title)
            self.assertEqual(data['doi'], self.pub_with_doi.doi)
            self.assertEqual(data['abstract'], self.pub_with_doi.abstract)

    def test_all_links_have_security_attributes(self):
        """Test that external links have target='_blank' and rel='noopener'."""
        response = self.client.get(f"/work/{self.pub_with_doi.doi}/")
        self.assertEqual(response.status_code, 200)

        # Check DOI link
        self.assertContains(response, 'target="_blank"')
        self.assertContains(response, 'rel="noopener"')

    def test_html_title_contains_publication_title_and_doi(self):
        """Test that the HTML <title> tag contains the publication title and DOI."""
        response = self.client.get(f"/work/{self.pub_with_doi.doi}/")
        self.assertEqual(response.status_code, 200)

        # Extract the title tag content
        content = response.content.decode('utf-8')

        # Check that <title> tag contains the publication title
        self.assertIn(f'<title>{self.pub_with_doi.title}', content)

        # Check that <title> tag contains the DOI in parentheses
        self.assertIn(f'({self.pub_with_doi.doi})', content)

        # Check that OPTIMAP is also in the title
        self.assertIn('OPTIMAP', content)

        # Verify the complete expected format: "Title (DOI) - OPTIMAP"
        expected_title = f'<title>{self.pub_with_doi.title} ({self.pub_with_doi.doi}) - OPTIMAP</title>'
        self.assertIn(expected_title, content)

    def test_html_title_format(self):
        """Test that the HTML <title> tag has proper format and structure."""
        response = self.client.get(f"/work/{self.pub_with_doi.doi}/")
        self.assertEqual(response.status_code, 200)

        # Verify title has opening and closing tags
        content = response.content.decode('utf-8')
        self.assertIn('<title>', content)
        self.assertIn('</title>', content)

        # Verify the title appears in the <head> section (use re.DOTALL for multiline)
        import re
        self.assertIsNotNone(re.search(r'<head>.*<title>.*</title>.*</head>', content, re.DOTALL))


class PublicationStatusVisibilityTest(TestCase):
    """Tests for publication status visibility controls."""

    def setUp(self):
        self.client = Client()

        # Create test source
        self.source = Source.objects.create(
            name="Test Journal",
            url_field="https://example.com/oai",
            homepage_url="https://example.com/journal",
            issn_l="1234-5678"
        )

        # Create publications with different statuses
        self.pub_published = Work.objects.create(
            title="Published Publication",
            abstract="This is published",
            url="https://example.com/published",
            status="p",  # Published
            doi="10.1234/published",
            publicationDate=now() - timedelta(days=30),
            geometry=GeometryCollection(Point(12.4924, 41.8902)),
            source=self.source
        )

        self.pub_draft = Work.objects.create(
            title="Draft Publication",
            abstract="This is a draft",
            url="https://example.com/draft",
            status="d",  # Draft
            doi="10.1234/draft",
            publicationDate=now() - timedelta(days=20),
            geometry=GeometryCollection(Point(13.4050, 52.5200)),
            source=self.source
        )

        self.pub_testing = Work.objects.create(
            title="Testing Publication",
            abstract="This is for testing",
            url="https://example.com/testing",
            status="t",  # Testing
            doi="10.1234/testing",
            publicationDate=now() - timedelta(days=10),
            source=self.source
        )

        self.pub_withdrawn = Work.objects.create(
            title="Withdrawn Publication",
            abstract="This is withdrawn",
            url="https://example.com/withdrawn",
            status="w",  # Withdrawn
            doi="10.1234/withdrawn",
            publicationDate=now() - timedelta(days=5),
            source=self.source
        )

        self.pub_harvested = Work.objects.create(
            title="Harvested Publication",
            abstract="This is harvested",
            url="https://example.com/harvested",
            status="h",  # Harvested
            doi="10.1234/harvested",
            publicationDate=now() - timedelta(days=3),
            source=self.source
        )

        # Create regular user
        self.regular_user = User.objects.create_user(
            username='regular@example.com',
            email='regular@example.com'
        )

        # Create admin user
        self.admin_user = User.objects.create_user(
            username='admin@example.com',
            email='admin@example.com',
            is_staff=True,
            is_superuser=True
        )

    def test_works_list_public_only_shows_published(self):
        """Test that non-authenticated users only see published works."""
        response = self.client.get('/works/')
        self.assertEqual(response.status_code, 200)

        # Should show published
        self.assertContains(response, self.pub_published.title)

        # Should NOT show other statuses
        self.assertNotContains(response, self.pub_draft.title)
        self.assertNotContains(response, self.pub_testing.title)
        self.assertNotContains(response, self.pub_withdrawn.title)
        self.assertNotContains(response, self.pub_harvested.title)

    def test_works_list_regular_user_only_shows_published(self):
        """Test that regular users only see published works."""
        self.client.force_login(self.regular_user)
        response = self.client.get('/works/')
        self.assertEqual(response.status_code, 200)

        # Should show published
        self.assertContains(response, self.pub_published.title)

        # Should NOT show other statuses
        self.assertNotContains(response, self.pub_draft.title)
        self.assertNotContains(response, self.pub_testing.title)

    def test_works_list_admin_shows_all_with_labels(self):
        """Test that admin users see all publications with status labels."""
        self.client.force_login(self.admin_user)
        response = self.client.get('/works/')
        self.assertEqual(response.status_code, 200)

        # Should show all publications
        self.assertContains(response, self.pub_published.title)
        self.assertContains(response, self.pub_draft.title)
        self.assertContains(response, self.pub_testing.title)
        self.assertContains(response, self.pub_withdrawn.title)
        self.assertContains(response, self.pub_harvested.title)

        # Should show status badges
        self.assertContains(response, 'Published')
        self.assertContains(response, 'Draft')
        self.assertContains(response, 'Testing')
        self.assertContains(response, 'Withdrawn')
        self.assertContains(response, 'Harvested')

        # Should show admin notice
        self.assertContains(response, 'Admin view')

    def test_work_landing_public_cannot_access_unpublished(self):
        """Test that non-authenticated users cannot access unpublished works."""
        # Published should work
        response = self.client.get(f'/work/{self.pub_published.doi}/')
        self.assertEqual(response.status_code, 200)

        # Draft should return 404
        response = self.client.get(f'/work/{self.pub_draft.doi}/')
        self.assertEqual(response.status_code, 404)

        # Testing should return 404
        response = self.client.get(f'/work/{self.pub_testing.doi}/')
        self.assertEqual(response.status_code, 404)

    def test_work_landing_regular_user_cannot_access_unpublished(self):
        """Test that regular users cannot access unpublished works."""
        self.client.force_login(self.regular_user)

        # Published should work
        response = self.client.get(f'/work/{self.pub_published.doi}/')
        self.assertEqual(response.status_code, 200)

        # Draft should return 404
        response = self.client.get(f'/work/{self.pub_draft.doi}/')
        self.assertEqual(response.status_code, 404)

    def test_work_landing_admin_can_access_all_with_label(self):
        """Test that admin users can access all publications with status labels."""
        self.client.force_login(self.admin_user)

        # Published should work without warning
        response = self.client.get(f'/work/{self.pub_published.doi}/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.pub_published.title)
        self.assertContains(response, 'Admin view')
        self.assertContains(response, 'Published')

        # Draft should work with warning
        response = self.client.get(f'/work/{self.pub_draft.doi}/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.pub_draft.title)
        self.assertContains(response, 'Admin view')
        self.assertContains(response, 'Draft')
        self.assertContains(response, 'not visible to the public')

        # Testing should work with warning
        response = self.client.get(f'/work/{self.pub_testing.doi}/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Testing')
        self.assertContains(response, 'not visible to the public')

    def test_api_viewset_queryset_filtering(self):
        """Test that WorkViewSet filters correctly based on user permissions."""
        from works.viewsets import WorkViewSet
        from rest_framework.test import APIRequestFactory
        from django.contrib.auth.models import AnonymousUser

        factory = APIRequestFactory()

        # Test anonymous user
        request = factory.get('/api/v1/works/')
        request.user = AnonymousUser()
        viewset = WorkViewSet()
        viewset.request = request
        queryset = viewset.get_queryset()

        # Should only return published
        self.assertIn(self.pub_published, queryset)
        self.assertNotIn(self.pub_draft, queryset)
        self.assertNotIn(self.pub_testing, queryset)

        # Test regular authenticated user
        request = factory.get('/api/v1/works/')
        request.user = self.regular_user
        viewset = WorkViewSet()
        viewset.request = request
        queryset = viewset.get_queryset()

        # Should only return published
        self.assertIn(self.pub_published, queryset)
        self.assertNotIn(self.pub_draft, queryset)

        # Test admin user
        request = factory.get('/api/v1/works/')
        request.user = self.admin_user
        viewset = WorkViewSet()
        viewset.request = request
        queryset = viewset.get_queryset()

        # Should return all publications
        self.assertIn(self.pub_published, queryset)
        self.assertIn(self.pub_draft, queryset)
        self.assertIn(self.pub_testing, queryset)
        self.assertIn(self.pub_withdrawn, queryset)
        self.assertIn(self.pub_harvested, queryset)


class MultipleIdentifierAccessTest(TestCase):
    """Tests for accessing works by various identifier types (DOI, ID, future: handle)."""

    def setUp(self):
        self.client = Client()

        # Create test source
        self.source = Source.objects.create(
            name="Test Journal",
            url_field="https://example.com/oai",
            homepage_url="https://example.com/journal",
            issn_l="1234-5678"
        )

        # Create a work with DOI
        self.work_with_doi = Work.objects.create(
            title="Work with DOI",
            abstract="This work has a DOI",
            url="https://example.com/work1",
            status="p",
            doi="10.1234/test-doi",
            publicationDate=now() - timedelta(days=30),
            geometry=GeometryCollection(Point(12.4924, 41.8902)),
            source=self.source
        )

        # Create a work without DOI
        self.work_without_doi = Work.objects.create(
            title="Work without DOI",
            abstract="This work has no DOI",
            url="https://example.com/work2",
            status="p",
            publicationDate=now() - timedelta(days=20),
            geometry=GeometryCollection(Point(13.4050, 52.5200)),
            source=self.source
        )

    def test_access_work_by_doi(self):
        """Test that a work can be accessed by its DOI."""
        response = self.client.get(f'/work/{self.work_with_doi.doi}/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.work_with_doi.title)
        self.assertContains(response, self.work_with_doi.doi)

    def test_access_work_by_internal_id(self):
        """Test that a work can be accessed by its internal ID."""
        response = self.client.get(f'/work/{self.work_with_doi.id}/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.work_with_doi.title)

    def test_access_work_without_doi_by_id(self):
        """Test that a work without DOI can be accessed by its internal ID."""
        response = self.client.get(f'/work/{self.work_without_doi.id}/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.work_without_doi.title)
        # Should not show DOI link since work has no DOI
        self.assertNotContains(response, 'https://doi.org/')

    def test_work_with_doi_prefers_doi_identifier(self):
        """Test that DOI is detected correctly even if ID could also match."""
        # DOI starts with "10." so should be detected as DOI
        response = self.client.get(f'/work/{self.work_with_doi.doi}/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.work_with_doi.title)

    def test_numeric_id_resolves_correctly(self):
        """Test that numeric IDs are handled correctly."""
        # Access by numeric ID
        response = self.client.get(f'/work/{self.work_with_doi.id}/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.work_with_doi.title)

    def test_invalid_identifier_returns_404(self):
        """Test that an invalid identifier returns 404."""
        response = self.client.get('/work/99999999/')  # Non-existent ID
        self.assertEqual(response.status_code, 404)

        response = self.client.get('/work/10.9999/nonexistent/')  # Non-existent DOI
        self.assertEqual(response.status_code, 404)

    def test_work_without_doi_title_format(self):
        """Test that works without DOI have correct title format (no DOI in parentheses)."""
        response = self.client.get(f'/work/{self.work_without_doi.id}/')
        self.assertEqual(response.status_code, 200)

        # Extract the title tag content
        content = response.content.decode('utf-8')

        # Should have title without DOI
        self.assertIn(f'<title>{self.work_without_doi.title} - OPTIMAP</title>', content)

        # Should NOT have DOI in parentheses
        self.assertNotIn(f'({self.work_without_doi.title})', content)

    def test_template_handles_null_doi(self):
        """Test that the template correctly handles works with null DOI."""
        response = self.client.get(f'/work/{self.work_without_doi.id}/')
        self.assertEqual(response.status_code, 200)

        # Should have title
        self.assertContains(response, self.work_without_doi.title)

        # Should NOT have DOI section
        self.assertNotContains(response, '<strong>DOI:</strong>')

        # JavaScript variables should handle empty DOI
        self.assertContains(response, 'const doi = ""')
        self.assertContains(response, 'const useIdUrls = true')

    def test_url_encoded_doi_works(self):
        """Test that URL-encoded DOIs are properly decoded and work."""
        # Create work with DOI that has special characters
        work = Work.objects.create(
            title="Work with special DOI",
            abstract="Test",
            status="p",
            doi="10.1234/test-doi/with-slash",
            source=self.source
        )

        # Django's URL routing should handle this automatically
        response = self.client.get(f'/work/{work.doi}/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, work.title)
