# SPDX-FileCopyrightText: 2022 OPTIMETA and KOMET projects <https://projects.tib.eu/komet>
# SPDX-License-Identifier: GPL-3.0-or-later

import os

from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from helium import *


class UsermenuTest(StaticLiveServerTestCase):
    def test_user_menu_dropdown(self):
        """Test user menu dropdown navigation."""
        start_chrome(f"{self.live_server_url}/", headless=True)
        try:
            click(S("#unifiedMenuDropdown"))
            get_driver().save_screenshot(os.path.join(os.getcwd(), "tests-ui", "screenshots", "UserMenu.png"))
        finally:
            kill_browser()
