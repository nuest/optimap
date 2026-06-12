# SPDX-FileCopyrightText: 2022 OPTIMETA and KOMET projects <https://projects.tib.eu/komet>
# SPDX-License-Identifier: GPL-3.0-or-later

import os

from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from helium import Button, Text, click, get_driver, kill_browser, start_chrome


class LoginconfirmationTest(StaticLiveServerTestCase):
    def test_login_confirmation_page(self):
        """Test that the login confirmation page loads correctly."""
        try:
            start_chrome(f"{self.live_server_url}/loginconfirm/", headless=True)
            get_driver().save_screenshot(os.path.join(os.getcwd(), "tests-ui", "screenshots", "UserMenu.png"))
            if Text("Welcome to OPTIMAP!").exists():
                click(Button("×"))
        finally:
            kill_browser()
