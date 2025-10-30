"""
UI tests for feeds pages and work landing pages.

Tests verify:
1. Feed pages load correctly with published works
2. Work landing pages display correctly
3. Navigation between feeds and works functions properly
"""

import os
from django.core.management import call_command
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from helium import (
    start_chrome,
    kill_browser,
    get_driver,
    Text,
    S,
    find_all,
    click,
    wait_until,
)

from works.models import Work


class FeedsAndWorkLandingTests(StaticLiveServerTestCase):
    """UI tests for feeds and work landing pages.

    Uses StaticLiveServerTestCase to automatically start a live test server
    that serves both the application and static files.
    """

    fixtures = ['test_data_optimap.json']

    @classmethod
    def setUpClass(cls):
        """Set up class-level resources including live server."""
        super().setUpClass()

        call_command("load_global_regions")

    def test_europe_feed_page_loads(self):
        """Test that the Europe feed page loads and displays works."""
        try:
            start_chrome(f'{self.live_server_url}/feeds/continent/europe/', headless=False)
            driver = get_driver()

            # Check page loaded
            self.assertIn("Europe", driver.title)

            # Check for feed page content
            page_text = driver.page_source.lower()
            self.assertTrue(
                'europe' in page_text and 'feed' in page_text,
                "Page should contain 'Europe' and 'feed'"
            )

            self.assertTrue(S('#feed-map').exists(), "Page should have a map")

            # Take screenshot
            screenshot_path = os.path.join(os.getcwd(), 'tests-ui', 'screenshots', 'europe_feed.png')
            driver.save_screenshot(screenshot_path)

        finally:
            kill_browser()

    def test_feeds_api_endpoint(self):
        """Test that the global GeoRSS API feed endpoint is accessible."""
        try:
            start_chrome(f'{self.live_server_url}/api/v1/feeds/optimap-global.rss', headless=True)
            driver = get_driver()

            # Check that page loaded (even if browser renders XML/RSS)
            self.assertIsNotNone(driver.page_source, "Page should have loaded")

            # Check the page is not a 404
            page_text = driver.page_source.lower()
            self.assertNotIn('page not found', page_text, "Should not be a 404 page")
            self.assertNotIn('error', page_text, "Should not be an error page")

            # Take screenshot
            screenshot_path = os.path.join(os.getcwd(), 'tests-ui', 'screenshots', 'global_feed_api.png')
            driver.save_screenshot(screenshot_path)

        finally:
            kill_browser()

    def test_work_landing_page_from_fixture(self):
        """Test that a work landing page loads correctly using fixture data."""
        # Get first published work from fixture
        work = Work.objects.filter(status='p').first()

        try:
            # Use the work's identifier (DOI or ID)
            identifier = work.get_identifier()
            start_chrome(f'{self.live_server_url}/work/{identifier}/', headless=False)
            driver = get_driver()

            # Check page loaded
            self.assertIn("OPTIMAP", driver.title)

            # Check for work title
            self.assertTrue(
                Text(work.title).exists() and work.title in driver.page_source,
                f"Page should contain work title: {work.title}"
            )

            page_text = driver.page_source.lower()
            self.assertTrue(
                'work' in page_text and work.title in page_text,
                "Page should be a work landing page showing the work title"
            )

            leaflet_paths = find_all(S('path.leaflet-interactive'))
            self.assertEqual(len(leaflet_paths), 3) # has geometries on the map from test_data_optimap.json
            for path in leaflet_paths:
                self.assertEqual(path.web_element.get_attribute('stroke'), '#158F9B')

            click(leaflet_paths[0])
        
            wait_until(lambda: Text('View work details').exists())

            # the last paper is the first in the paths
            self.assertIn('Visit work', S('div.leaflet-popup-content').web_element.text)
            self.assertIn('Paper 3', S('div.leaflet-popup-content').web_element.text)
            self.assertIn('OPTIMAP Test Journal', S('div.leaflet-popup-content').web_element.text)
            self.assertIn('better? Dresden!', S('div.leaflet-popup-content').web_element.text)

            # Take screenshot
            screenshot_path = os.path.join(os.getcwd(), 'tests-ui', 'screenshots', 'work_landing.png')
            driver.save_screenshot(screenshot_path)
        finally:
            kill_browser()

    def test_work_landing_page_with_doi(self):
        """Test that a work landing page can be accessed via DOI."""
        # Get a work with DOI from fixture
        work = Work.objects.filter(status='p', doi__isnull=False).first()

        if not work:
            self.skipTest('No published works with DOI in fixtures')

        try:
            # Access via DOI
            start_chrome(f'{self.live_server_url}/work/{work.doi}/', headless=True)
            driver = get_driver()

            # Check page loaded
            self.assertIn("OPTIMAP", driver.title)

            # Check DOI is displayed
            self.assertTrue(
                work.doi in driver.page_source,
                f"Page should display DOI: {work.doi}"
            )

            # Take screenshot
            screenshot_path = os.path.join(os.getcwd(), 'tests-ui', 'screenshots', 'work_landing_doi.png')
            driver.save_screenshot(screenshot_path)

        finally:
            kill_browser()

    def test_work_landing_page_without_doi(self):
        """Test that a work landing page can be accessed via ID when no DOI."""
        # Get a work without DOI from fixture
        work = Work.objects.filter(status='p', doi__isnull=True).first()

        if not work:
            # If all works have DOI, just test with ID instead
            work = Work.objects.filter(status='p').first()
            if not work:
                self.skipTest('No published works in fixtures')

        try:
            # Access via internal ID
            start_chrome(f'{self.live_server_url}/work/{work.id}/', headless=True)
            driver = get_driver()

            # Check page loaded
            self.assertIn("OPTIMAP", driver.title)

            # Check work title is displayed
            self.assertTrue(
                work.title in driver.page_source,
                f"Page should display work title: {work.title}"
            )

            # Take screenshot
            screenshot_path = os.path.join(os.getcwd(), 'tests-ui', 'screenshots', 'work_landing_id.png')
            driver.save_screenshot(screenshot_path)

        finally:
            kill_browser()

    def test_feeds_listing_page(self):
        """Test that the feeds listing page loads and shows available feeds."""
        try:
            start_chrome(f'{self.live_server_url}/feeds/', headless=True)
            driver = get_driver()

            # Check page loaded
            self.assertIn("OPTIMAP", driver.title)

            # Check for feeds page content
            page_text = driver.page_source.lower()
            self.assertTrue(
                'feed' in page_text or 'rss' in page_text or 'atom' in page_text,
                "Page should mention feeds, RSS, or Atom"
            )

            # Take screenshot
            screenshot_path = os.path.join(os.getcwd(), 'tests-ui', 'screenshots', 'feeds_listing.png')
            driver.save_screenshot(screenshot_path)

        finally:
            kill_browser()
