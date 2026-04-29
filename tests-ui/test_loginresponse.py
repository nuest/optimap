# SPDX-FileCopyrightText: 2022 OPTIMETA and KOMET projects <https://projects.tib.eu/komet>
# SPDX-License-Identifier: GPL-3.0-or-later

from django.contrib.staticfiles.testing import StaticLiveServerTestCase
import os
from helium import *
import time

class LoginresponseTest(StaticLiveServerTestCase):
    def test_login_response(self):
        """Test login flow and response message."""
        start_chrome(f'{self.live_server_url}/', headless=True)
        try:
            click(Button("signup"))
            write('dev@example.com', into='email')
            get_driver().save_screenshot(os.path.join(os.getcwd(), 'tests-ui', 'screenshots', 'Loginmailid.png'))
            click("Login")
            # time to allow loading
            time.sleep(2)
            get_driver().save_screenshot(os.path.join(os.getcwd(), 'tests-ui', 'screenshots', 'Loginresponse.png'))
            if Text("Awesome!").exists():
                click(Button("×"))
        finally:
            kill_browser()
