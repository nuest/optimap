from django.test import TestCase, Client
from django.urls import reverse
from publications.models import Publication, Source
from django.contrib.gis.geos import Point, GeometryCollection
from django.utils.timezone import now
from datetime import timedelta


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
