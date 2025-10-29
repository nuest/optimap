"""
UI tests for public pages that can be accessed without authentication.
Tests verify:
1. Pages load successfully (200 status)
2. Expected content is present
3. No admin-only content is visible to anonymous users
"""

from django.test import TestCase
from django.urls import reverse
from helium import (
    start_chrome,
    kill_browser,
    get_driver,
    Text,
    S,
)


class PublicPagesBasicTests(TestCase):
    """Basic tests for all public pages - ensure they load and contain expected content."""

    fixtures = ['test_data_optimap.json', 'test_data_global_feeds.json']

    def test_about_page(self):
        """Test about page loads with expected content."""
        response = self.client.get(reverse("optimap:about"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "About")
        self.assertContains(response, "OPTIMAP")
        # Should not contain admin links
        self.assertNotContains(response, "/admin/")
        self.assertNotContains(response, "Django administration")

    def test_accessibility_page(self):
        """Test accessibility page loads with expected content."""
        response = self.client.get(reverse("optimap:accessibility"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Accessibility")
        # Should not contain admin links
        self.assertNotContains(response, "/admin/")

    def test_privacy_page(self):
        """Test privacy page loads with expected content."""
        response = self.client.get(reverse("optimap:privacy"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Privacy")
        # Should not contain admin links
        self.assertNotContains(response, "/admin/")

    def test_data_page(self):
        """Test data page loads with API documentation."""
        response = self.client.get(reverse("optimap:data"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Data")
        self.assertContains(response, "API")
        # Should not contain admin links
        self.assertNotContains(response, "/admin/")

    def test_sitemap_page(self):
        """Test sitemap page loads with links."""
        response = self.client.get(reverse("optimap:sitemap-page"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Sitemap")
        # Should not contain admin links
        self.assertNotContains(response, "/admin/")

    def test_feeds_listing_page(self):
        """Test feeds listing page loads with feed links."""
        response = self.client.get(reverse("optimap:feeds"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Feeds")
        self.assertContains(response, "RSS")
        # Should not contain admin links
        self.assertNotContains(response, "/admin/")

    def test_contribute_page(self):
        """Test contribute page loads with works list."""
        response = self.client.get(reverse("optimap:contribute"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Contribute")
        # Should not contain admin links for anonymous users
        self.assertNotContains(response, "Django administration")

    def test_works_list_page(self):
        """Test works list page loads."""
        response = self.client.get(reverse("optimap:works"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Works")
        # Should not contain admin links
        self.assertNotContains(response, "/admin/")

    def test_main_page(self):
        """Test main map page loads."""
        response = self.client.get(reverse("optimap:main"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "OPTIMAP")
        # Should not contain admin links
        self.assertNotContains(response, "/admin/")

    def test_geoextent_page(self):
        """Test geoextent page loads."""
        response = self.client.get(reverse("optimap:geoextent"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Geoextent")
        # Should not contain admin links
        self.assertNotContains(response, "/admin/")


class RegionalFeedPagesTests(TestCase):
    """Tests for regional feed landing pages."""

    fixtures = ['test_data_global_feeds.json']

    def test_continent_feed_page_loads(self):
        """Test that a continent feed page loads successfully."""
        # First check if global regions are loaded
        from works.models import GlobalRegion
        if not GlobalRegion.objects.exists():
            self.skipTest('Global regions not loaded - run load_global_regions management command')

        response = self.client.get('/feeds/continent/europe/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Europe")
        # Should not contain admin links
        self.assertNotContains(response, "/admin/")

    def test_ocean_feed_page_loads(self):
        """Test that an ocean feed page loads successfully."""
        # First check if global regions are loaded
        from works.models import GlobalRegion
        if not GlobalRegion.objects.exists():
            self.skipTest('Global regions not loaded - run load_global_regions management command')

        response = self.client.get('/feeds/ocean/north-atlantic-ocean/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "North Atlantic Ocean")
        # Should not contain admin links
        self.assertNotContains(response, "/admin/")


class PublicPagesBrowserTests(TestCase):
    """Browser-based tests for public pages using Helium."""

    fixtures = ['test_data_optimap.json']

    def test_about_page_browser(self):
        """Test about page renders correctly in browser."""
        try:
            start_chrome('localhost:8000/about/', headless=True)
            driver = get_driver()

            # Check page loaded
            self.assertIn("OPTIMAP", driver.title)

            # Check expected content exists
            self.assertTrue(Text("About").exists())

            # Verify no admin panel links visible
            admin_links = driver.find_elements("xpath", "//a[contains(@href, '/admin/')]")
            self.assertEqual(len(admin_links), 0, "Admin links should not be visible to anonymous users")

        finally:
            kill_browser()

    def test_data_page_browser(self):
        """Test data page renders correctly in browser."""
        try:
            start_chrome('localhost:8000/data/', headless=True)
            driver = get_driver()

            # Check page loaded
            self.assertIn("OPTIMAP", driver.title)

            # Check expected content exists
            self.assertTrue(Text("Data").exists() or Text("API").exists())

            # Verify no admin panel links visible
            admin_links = driver.find_elements("xpath", "//a[contains(@href, '/admin/')]")
            self.assertEqual(len(admin_links), 0, "Admin links should not be visible to anonymous users")

        finally:
            kill_browser()

    def test_accessibility_page_browser(self):
        """Test accessibility page renders correctly in browser."""
        try:
            start_chrome('localhost:8000/accessibility/', headless=True)
            driver = get_driver()

            # Check page loaded
            self.assertIn("OPTIMAP", driver.title)

            # Check expected content exists
            self.assertTrue(Text("Accessibility").exists())

            # Verify no admin panel links visible
            admin_links = driver.find_elements("xpath", "//a[contains(@href, '/admin/')]")
            self.assertEqual(len(admin_links), 0, "Admin links should not be visible to anonymous users")

        finally:
            kill_browser()
