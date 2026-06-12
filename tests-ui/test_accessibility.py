# SPDX-FileCopyrightText: 2026 OPTIMAP and KOMET projects <https://projects.tib.eu/komet>
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Browser-based accessibility tests using axe-core via axe-selenium-python.

Each axe check injects axe-core into a real browser page and asserts that
there are no critical or serious WCAG violations. Targeted tests then verify
specific ARIA attributes added by issue #173.

Run with:
    python -Wa manage.py test tests-ui.test_accessibility
"""

import json
import os

from axe_selenium_python import Axe
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from helium import get_driver, kill_browser, start_chrome, wait_until


class AccessibilityAuditTests(StaticLiveServerTestCase):
    fixtures = ["test_data_optimap.json", "test_data_global_feeds.json"]

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.screenshot_dir = os.path.join(os.getcwd(), "tests-ui", "screenshots")
        os.makedirs(cls.screenshot_dir, exist_ok=True)

    def _axe_check(self, path, page_name, wait_selector=None):
        """Load the page, optionally wait for a CSS selector, inject axe-core, assert no critical/serious violations."""
        try:
            start_chrome(f"{self.live_server_url}{path}", headless=True)
            driver = get_driver()
            if wait_selector:
                wait_until(
                    lambda: driver.find_elements("css selector", wait_selector),
                    timeout_secs=10,
                )
            axe = Axe(driver)
            axe.inject()
            results = axe.run()
            violations = [v for v in results["violations"] if v["impact"] in ("critical", "serious")]
            self.assertEqual(
                [],
                violations,
                f"axe-core found {len(violations)} critical/serious violation(s) on {page_name}:\n"
                + json.dumps(
                    [
                        {
                            "id": v["id"],
                            "impact": v["impact"],
                            "description": v["description"],
                            "nodes": len(v["nodes"]),
                        }
                        for v in violations
                    ],
                    indent=2,
                ),
            )
        finally:
            kill_browser()

    # ------------------------------------------------------------------ #
    # Broad axe-core scans — one per public page                          #
    # ------------------------------------------------------------------ #

    def test_home_page_a11y(self):
        self._axe_check("/", "home page", wait_selector="#map")

    def test_works_list_a11y(self):
        self._axe_check("/works/list/", "works listing")

    def test_about_page_a11y(self):
        self._axe_check("/about/", "about page")

    def test_accessibility_statement_a11y(self):
        self._axe_check("/accessibility/", "accessibility statement")

    def test_contribute_page_a11y(self):
        self._axe_check("/contribute/", "contribute page")

    def test_statistics_page_a11y(self):
        self._axe_check("/statistics/", "statistics page")

    # ------------------------------------------------------------------ #
    # Targeted ARIA attribute assertions                                   #
    # ------------------------------------------------------------------ #

    def test_map_div_has_role_application(self):
        try:
            start_chrome(f"{self.live_server_url}/", headless=True)
            driver = get_driver()
            wait_until(lambda: driver.find_elements("id", "map"), timeout_secs=10)
            map_div = driver.find_element("id", "map")
            self.assertEqual("application", map_div.get_attribute("role"))
            self.assertIsNotNone(map_div.get_attribute("aria-label"))
        finally:
            kill_browser()

    def test_skip_link_targets_main_content(self):
        try:
            start_chrome(f"{self.live_server_url}/", headless=True)
            driver = get_driver()
            skip_link = driver.find_element("css selector", "a.skip-link")
            self.assertTrue(
                skip_link.get_attribute("href").endswith("#main-content"),
                "Skip link must point to #main-content",
            )
        finally:
            kill_browser()

    def test_about_page_no_bare_here_link(self):
        try:
            start_chrome(f"{self.live_server_url}/about/", headless=True)
            driver = get_driver()
            links = driver.find_elements("tag name", "a")
            bare = [l for l in links if l.text.strip().lower() == "here"]
            self.assertEqual([], bare, "Found bare 'here' link text on about page")
        finally:
            kill_browser()

    def test_statistics_table_headers_have_scope(self):
        try:
            start_chrome(f"{self.live_server_url}/statistics/", headless=True)
            driver = get_driver()
            th_elements = driver.find_elements("css selector", "table th")
            for th in th_elements:
                self.assertEqual(
                    "col",
                    th.get_attribute("scope"),
                    f"<th> missing scope='col': text='{th.text}'",
                )
        finally:
            kill_browser()

    def test_menu_dividers_are_aria_hidden(self):
        try:
            start_chrome(f"{self.live_server_url}/", headless=True)
            driver = get_driver()
            dividers = driver.find_elements("css selector", ".dropdown-divider")
            for divider in dividers:
                self.assertEqual(
                    "true",
                    divider.get_attribute("aria-hidden"),
                    "Dropdown divider must have aria-hidden='true'",
                )
        finally:
            kill_browser()
