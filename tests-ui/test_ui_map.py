from unittest import TestCase
from helium import *

class SimpleTest(TestCase):

    def test_map_page(self):
        start_chrome('localhost:8000/', headless=True)

        get_driver().save_screenshot(r'tests-ui/screenshots/map.png')

        self.assertTrue(S('#map').exists())

        leaflet_paths = find_all(S('path.leaflet-interactive'))
        self.assertGreater(len(leaflet_paths), 0) # has geometries on the map
        for path in leaflet_paths:
            self.assertEqual(path.web_element.get_attribute('stroke'), '#158F9B')

        click(leaflet_paths[0])

        wait_until(lambda: Text('View work details').exists())

        # we do not know which popup, so we cannot test for much
        self.assertIn('Visit work', S('div.leaflet-popup-content').web_element.text)

        get_driver().save_screenshot(r'tests-ui/screenshots/map_popup.png')

        # continue: click(link('Visit Article'))

        kill_browser()
