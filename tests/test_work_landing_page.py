from django.test import TestCase, Client
from django.urls import reverse
from publications.models import Publication, Source
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
        self.pub_with_doi = Publication.objects.create(
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

        self.pub_no_homepage = Publication.objects.create(
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
        expected_api_url = f'/api/v1/publications/{self.pub_with_doi.id}/'
        self.assertContains(response, expected_api_url)
        self.assertContains(response, 'View raw JSON from API')

    def test_raw_json_api_returns_valid_json(self):
        """Test that the raw JSON API endpoint returns valid JSON data."""
        # First get the work landing page to ensure publication exists
        response = self.client.get(f"/work/{self.pub_with_doi.doi}/")
        self.assertEqual(response.status_code, 200)

        # Now test the API endpoint
        api_response = self.client.get(f'/api/v1/publications/{self.pub_with_doi.id}/')
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
        self.pub_published = Publication.objects.create(
            title="Published Publication",
            abstract="This is published",
            url="https://example.com/published",
            status="p",  # Published
            doi="10.1234/published",
            publicationDate=now() - timedelta(days=30),
            geometry=GeometryCollection(Point(12.4924, 41.8902)),
            source=self.source
        )

        self.pub_draft = Publication.objects.create(
            title="Draft Publication",
            abstract="This is a draft",
            url="https://example.com/draft",
            status="d",  # Draft
            doi="10.1234/draft",
            publicationDate=now() - timedelta(days=20),
            geometry=GeometryCollection(Point(13.4050, 52.5200)),
            source=self.source
        )

        self.pub_testing = Publication.objects.create(
            title="Testing Publication",
            abstract="This is for testing",
            url="https://example.com/testing",
            status="t",  # Testing
            doi="10.1234/testing",
            publicationDate=now() - timedelta(days=10),
            source=self.source
        )

        self.pub_withdrawn = Publication.objects.create(
            title="Withdrawn Publication",
            abstract="This is withdrawn",
            url="https://example.com/withdrawn",
            status="w",  # Withdrawn
            doi="10.1234/withdrawn",
            publicationDate=now() - timedelta(days=5),
            source=self.source
        )

        self.pub_harvested = Publication.objects.create(
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
        """Test that PublicationViewSet filters correctly based on user permissions."""
        from publications.viewsets import PublicationViewSet
        from rest_framework.test import APIRequestFactory
        from django.contrib.auth.models import AnonymousUser

        factory = APIRequestFactory()

        # Test anonymous user
        request = factory.get('/api/v1/publications/')
        request.user = AnonymousUser()
        viewset = PublicationViewSet()
        viewset.request = request
        queryset = viewset.get_queryset()

        # Should only return published
        self.assertIn(self.pub_published, queryset)
        self.assertNotIn(self.pub_draft, queryset)
        self.assertNotIn(self.pub_testing, queryset)

        # Test regular authenticated user
        request = factory.get('/api/v1/publications/')
        request.user = self.regular_user
        viewset = PublicationViewSet()
        viewset.request = request
        queryset = viewset.get_queryset()

        # Should only return published
        self.assertIn(self.pub_published, queryset)
        self.assertNotIn(self.pub_draft, queryset)

        # Test admin user
        request = factory.get('/api/v1/publications/')
        request.user = self.admin_user
        viewset = PublicationViewSet()
        viewset.request = request
        queryset = viewset.get_queryset()

        # Should return all publications
        self.assertIn(self.pub_published, queryset)
        self.assertIn(self.pub_draft, queryset)
        self.assertIn(self.pub_testing, queryset)
        self.assertIn(self.pub_withdrawn, queryset)
        self.assertIn(self.pub_harvested, queryset)
