from django.contrib.staticfiles.testing import StaticLiveServerTestCase
import os
from helium import start_chrome, get_driver, click, Text, Button, kill_browser

class LoginconfirmationTest(StaticLiveServerTestCase):

    def test_login_confirmation_page(self):
        """Test that the login confirmation page loads correctly."""
        try:
            start_chrome(f'{self.live_server_url}/loginconfirm/', headless=True)
            get_driver().save_screenshot(os.path.join(os.getcwd(), 'tests-ui', 'screenshots', 'UserMenu.png'))
            if Text("Welcome to OPTIMAP!").exists():
                click(Button("×"))
        finally:
            kill_browser()
    