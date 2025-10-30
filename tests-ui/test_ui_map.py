import os

import django
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from helium import *
from datetime import date

from works.models import Work
from django.contrib.gis.geos import Point, MultiPoint, LineString, Polygon, GeometryCollection
from django.contrib.auth import get_user_model

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'optimap.settings')
django.setup()

User = get_user_model()


class SimpleTest(StaticLiveServerTestCase):
    """UI tests for the map page.

    Uses StaticLiveServerTestCase to automatically start a live test server
    that serves both the application and static files.
    """

    # Load test data fixtures into the test database
    fixtures = ['test_data_optimap.json']

    @classmethod
    def setUpClass(cls):
        """Set up class-level resources including live server."""
        super().setUpClass()

    def setUp(self):
        """Set up for each test."""
        pass

    def test_map_page(self):
        """Test that the map page loads and displays geometries correctly."""
        # Use self.live_server_url which is automatically provided by StaticLiveServerTestCase
        start_chrome(f'{self.live_server_url}/', headless=True)

        get_driver().save_screenshot(r'tests-ui/screenshots/map.png')

        self.assertTrue(S('#map').exists())

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

        get_driver().save_screenshot(r'tests-ui/screenshots/map_popup.png')

        # continue: click(link('Visit Article'))

        kill_browser()
