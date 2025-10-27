from django.test import TestCase
from django.contrib.gis.geos import MultiPolygon, Polygon
from http import HTTPStatus
from publications.models import GlobalRegion

class SitemapTest(TestCase):
    def test_index(self):
        response = self.client.get("/sitemap.xml")
        self.assertEqual(response.status_code, HTTPStatus.OK)
        self.assertEqual(response["content-type"], "application/xml")

    def test_static(self):
        response = self.client.get("/sitemap-static.xml")
        self.assertEqual(response.status_code, HTTPStatus.OK)
        self.assertEqual(response["content-type"], "application/xml")

    def test_publications(self):
        response = self.client.get("/sitemap-publications.xml")
        self.assertEqual(response.status_code, HTTPStatus.OK)
        self.assertEqual(response["content-type"], "application/xml")
        # TODO test content

    def test_feeds(self):
        """Test feeds sitemap generation for global regions."""
        response = self.client.get("/sitemap-feeds.xml")
        self.assertEqual(response.status_code, HTTPStatus.OK)
        self.assertEqual(response["content-type"], "application/xml")

    def test_feeds_content(self):
        """Test feeds sitemap includes regional feed URLs."""
        # Create test GlobalRegion instances
        test_polygon = MultiPolygon(Polygon(((0, 0), (0, 1), (1, 1), (1, 0), (0, 0))))

        continent = GlobalRegion.objects.create(
            name="Test Continent",
            region_type=GlobalRegion.CONTINENT,
            source_url="http://example.com",
            license="CC BY 4.0",
            geom=test_polygon
        )

        ocean = GlobalRegion.objects.create(
            name="Test Ocean",
            region_type=GlobalRegion.OCEAN,
            source_url="http://example.com",
            license="CC BY 4.0",
            geom=test_polygon
        )

        # Get the feeds sitemap
        response = self.client.get("/sitemap-feeds.xml")
        content = response.content.decode('utf-8')

        # Verify response
        self.assertEqual(response.status_code, HTTPStatus.OK)
        self.assertIn('<?xml version="1.0" encoding="UTF-8"?>', content)
        self.assertIn('<urlset', content)

        # Verify continent feed URL is included
        self.assertIn('/feeds/continent/test-continent/', content)

        # Verify ocean feed URL is included
        self.assertIn('/feeds/ocean/test-ocean/', content)

        # Verify priority and changefreq
        self.assertIn('<priority>0.6</priority>', content)
        self.assertIn('<changefreq>daily</changefreq>', content)

    def test_feeds_index_reference(self):
        """Test that feeds sitemap is referenced in main sitemap index.

        Note: Django's sitemap index only includes sitemaps that have items.
        This test creates GlobalRegion objects to ensure the feeds sitemap
        appears in the index.
        """
        # Create at least one GlobalRegion so the feeds sitemap has items
        test_polygon = MultiPolygon(Polygon(((0, 0), (0, 1), (1, 1), (1, 0), (0, 0))))
        GlobalRegion.objects.create(
            name="Test Region",
            region_type=GlobalRegion.CONTINENT,
            source_url="http://example.com",
            license="CC BY 4.0",
            geom=test_polygon
        )

        response = self.client.get("/sitemap.xml")
        content = response.content.decode('utf-8')

        self.assertEqual(response.status_code, HTTPStatus.OK)
        # Verify the feeds sitemap is listed in the index
        self.assertIn('sitemap-feeds.xml', content)
