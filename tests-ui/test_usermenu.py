from django.contrib.staticfiles.testing import StaticLiveServerTestCase
import os
from helium import *

class UsermenuTest(StaticLiveServerTestCase):
    def test_user_menu_dropdown(self):
        """Test user menu dropdown navigation."""
        start_chrome(f'{self.live_server_url}/', headless=True)
        try:
            click(S("#navbarDarkDropdown"))
            get_driver().save_screenshot(os.path.join(os.getcwd(), 'tests-ui', 'screenshots', 'UserMenu.png'))
        finally:
            kill_browser()
