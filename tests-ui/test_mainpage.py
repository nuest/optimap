import os
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from helium import start_chrome, get_driver, kill_browser


class MainpageTest(StaticLiveServerTestCase):
    """UI test for the main page.

    Uses StaticLiveServerTestCase to automatically start a live test server
    that serves both the application and static files.
    """

    fixtures = ['test_data_optimap.json']

    @classmethod
    def setUpClass(cls):
        """Set up class-level resources including live server."""
        super().setUpClass()

    def test_mainpage_loads(self):
        """Test that the main page loads correctly."""
        start_chrome(f'{self.live_server_url}/')
        get_driver().save_screenshot(os.path.join(os.getcwd(), 'tests-ui', 'screenshots', 'UserMenu.png'))
        kill_browser()
