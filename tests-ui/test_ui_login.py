import os
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from helium import *

class SimpleTest(StaticLiveServerTestCase):

    def test_login_page(self):
        start_chrome(f'{self.live_server_url}/login/', headless=True)

        write('optimap@dev.dev', into='email')

        get_driver().save_screenshot(os.path.join(os.getcwd(), 'tests-ui', 'screenshots', 'login-email.png'))

        click("Send")

        wait_until(lambda: Text('Success!').exists())

        self.assertIn('Check your email', S('body').web_element.text)

        get_driver().save_screenshot(r'tests-ui/screenshots/login-success.png')

        kill_browser()
