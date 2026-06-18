# SPDX-FileCopyrightText: 2026 OPTIMETA and KOMET projects <https://projects.tib.eu/komet>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Browser regression test for the staff 'schedule statistics recomputation' button.

The recompute endpoint (POST /api/v1/statistics/recompute/) is DRF
session-authenticated, so the browser must send a valid CSRF token. The unit
tests use Django's test client with CSRF enforcement disabled, so they cannot
catch a missing/empty X-CSRFToken header — which is exactly the bug that made
the button silently fail (the request was rejected with 403 and no task was
enqueued). This test drives a real headless browser to verify the full path:
click -> 202 -> success message shown.
"""

import re
import time
from importlib import import_module

from django.conf import settings
from django.contrib.auth import (
    BACKEND_SESSION_KEY,
    HASH_SESSION_KEY,
    SESSION_KEY,
    get_user_model,
)
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from helium import get_driver, kill_browser, start_chrome
from selenium.webdriver.common.by import By

User = get_user_model()


class StatisticsRecomputeButtonTests(StaticLiveServerTestCase):
    def setUp(self):
        self.staff = User.objects.create_superuser(username="admin", email="admin@example.com", password="pw")

    def _login_in_browser(self, driver):
        """Inject a session cookie so the live-server browser is authenticated as staff."""
        engine = import_module(settings.SESSION_ENGINE)
        session = engine.SessionStore()
        session[SESSION_KEY] = str(self.staff.pk)
        session[BACKEND_SESSION_KEY] = settings.AUTHENTICATION_BACKENDS[0]
        session[HASH_SESSION_KEY] = self.staff.get_session_auth_hash()
        session.save()
        driver.add_cookie({"name": settings.SESSION_COOKIE_NAME, "value": session.session_key, "path": "/"})

    def test_staff_click_schedules_recompute(self):
        try:
            # Load any page first so the cookie can be set for the domain, then
            # authenticate and (re)load the statistics page as staff.
            start_chrome(f"{self.live_server_url}/", headless=True)
            driver = get_driver()
            self._login_in_browser(driver)
            driver.get(f"{self.live_server_url}/statistics/")

            buttons = driver.find_elements(By.ID, "calcNowBtn")
            self.assertEqual(len(buttons), 1, "staff should see the recompute button")
            button = buttons[0]
            self.assertTrue(button.get_attribute("data-csrf"), "button must carry a CSRF token")

            button.click()

            # The success branch only runs on a 202 response, which requires the
            # CSRF token to have been accepted by DRF.
            status = driver.find_element(By.ID, "calcNowStatus")
            deadline = time.time() + 10
            while time.time() < deadline and not status.text.strip():
                time.sleep(0.2)

            self.assertIn("scheduled", status.text.lower(), f"unexpected status text: {status.text!r}")
            self.assertIn("text-success", status.get_attribute("class"))
            self.assertNotIn("text-danger", status.get_attribute("class"))
            # The human-readable Django-Q task name is shown, e.g. "(task ceiling-mississippi-gee-delta)".
            match = re.search(r"\(task ([a-z-]+)\)", status.text)
            self.assertIsNotNone(match, f"task name missing from status: {status.text!r}")
            self.assertTrue(match.group(1))
        finally:
            kill_browser()
