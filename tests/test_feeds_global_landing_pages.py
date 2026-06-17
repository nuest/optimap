# SPDX-FileCopyrightText: 2025 OPTIMETA and KOMET projects <https://projects.tib.eu/komet>
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Tests for regional feed landing pages.

These tests verify that the feed landing pages correctly display
works filtered by region.
"""

import os
import shutil
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "optimap.settings")
import django

django.setup()

from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse

from works.models import GlobalRegion, Work

NSPS = {"atom": "http://www.w3.org/2005/Atom"}


# Tiny fixture geojson files (committed under tests/fixtures/global_regions/)
# are copied into a tmpdir before load_global_regions runs, so the command
# skips network downloads and loads our deterministic, low-fidelity geometries.
FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "global_regions"


# Expected work counts per region against the *tiny* simplified geometries in
# tests/fixtures/global_regions/. Regenerate by hand or by running the test suite
# and reading the failure messages whenever the fixture or tests/fixtures/global_regions/
# geometries change.
EXPECTED_COUNTS = {
    # Continents
    "africa": 12,
    "antarctica": 1,
    "asia": 23,
    "australia": 7,
    "europe": 20,
    "north-america": 13,
    "oceania": 2,
    "south-america": 8,
    # Oceans
    "arctic-ocean": 10,
    "baltic-sea": 6,
    "indian-ocean": 18,
    "mediterranean-region": 14,
    "north-atlantic-ocean": 22,
    "north-pacific-ocean": 18,
    "south-atlantic-ocean": 13,
    "south-china-and-easter-archipelagic-seas": 10,
    "south-pacific-ocean": 9,
    "southern-ocean": 6,
}


def _install_global_region_fixtures(target_dir):
    """Copy the tiny fixture files into target_dir and create a placeholder GPKG.

    load_global_regions skips the Marine Regions ZIP download when goas_v01.gpkg
    already exists, and skips re-simplification when goas_v01_simplified.geojson
    already exists. The placeholder gpkg is never read because the simplified
    file is present.
    """
    target = Path(target_dir)
    target.mkdir(parents=True, exist_ok=True)
    shutil.copy(FIXTURE_DIR / "world_continents.geojson", target / "world_continents.geojson")
    shutil.copy(FIXTURE_DIR / "goas_v01_simplified.geojson", target / "goas_v01_simplified.geojson")
    (target / "goas_v01.gpkg").touch()


class GlobalFeedsAndLandingPageTests(TestCase):
    fixtures = ["test_data_global_feeds"]

    @classmethod
    def setUpClass(cls):
        cls._regions_tmp = tempfile.mkdtemp(prefix="optimap_global_regions_")
        _install_global_region_fixtures(cls._regions_tmp)
        cls._settings_override = override_settings(GLOBAL_REGIONS_DATA_DIR=cls._regions_tmp)
        cls._settings_override.enable()
        super().setUpClass()

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        cls._settings_override.disable()
        shutil.rmtree(cls._regions_tmp, ignore_errors=True)

    @classmethod
    def setUpTestData(cls):
        call_command("flush", "--no-input")
        call_command("load_global_regions")
        call_command("loaddata", "test_data_global_feeds")

    def slugify(self, name):
        """Convert region name to slug."""
        return name.lower().replace(" ", "-")

    def test_global_region_load(self):
        regions = GlobalRegion.objects.all()
        self.assertEqual(len(regions), 18)  # 8 continents + 10 oceans

    def test_georss_feed_per_region(self):
        for region in GlobalRegion.objects.all():
            slug = self.slugify(region.name)
            # Use new API v1 endpoint based on region type
            if region.region_type == "continent":
                url = reverse("optimap:api-continent-georss", kwargs={"continent_slug": slug})
            else:  # ocean
                url = reverse("optimap:api-ocean-georss", kwargs={"ocean_slug": slug})

            resp = self.client.get(url)
            self.assertEqual(resp.status_code, 200, f"{region.name} GeoRSS feed failed")

            root = ET.fromstring(resp.content)
            titles = [item.find("title").text for item in root.findall(".//item")]

            expected_titles = list(
                Work.objects.filter(status="p", geometry__isnull=False, geometry__intersects=region.geom)
                .order_by("-creationDate")
                .values_list("title", flat=True)
            )

            self.assertCountEqual(
                titles,
                expected_titles,
                f"GeoRSS feed for {region.name} returned {titles!r}, expected {expected_titles!r}",
            )

    def test_geoatom_feed_australia(self):
        # Use new API v1 Atom endpoint
        url = reverse("optimap:api-continent-atom", kwargs={"continent_slug": "australia"})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        root = ET.fromstring(response.content)
        titles = [
            entry.find("atom:title", namespaces=NSPS).text for entry in root.findall(".//atom:entry", namespaces=NSPS)
        ]

        self.assertEqual(len(titles), 7, "Atom feed for Australia should return 7 entries")
        self.assertEqual(
            titles[0],
            "Marine Biology and Oceanography of the South China and Easter Archipelagic Seas",
            "Atom feed for Australia returned unexpected title",
        )

    def test_georss_feed_south_atlantic(self):
        # Use new API v1 GeoRSS endpoint
        url = reverse("optimap:api-ocean-georss", kwargs={"ocean_slug": "south-atlantic-ocean"})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        root = ET.fromstring(response.content)
        titles = [item.find("title").text for item in root.findall(".//item", namespaces=NSPS)]

        self.assertEqual(len(titles), 13, "GeoRSS feed for South Atlantic Ocean should return 13 entries")
        self.assertEqual(
            titles[0], "Pan-Pacific Study", "GeoRSS feed for South Atlantic Ocean returned unexpected first title"
        )
        self.assertEqual(
            titles[-1],
            "Seismic Survey: Mid-Atlantic Ridge",
            "GeoRSS feed for South Atlantic Ocean returned unexpected last title",
        )

    def test_all_continent_pages_display_correct_work_counts(self):
        """Test that all continent feed pages display the correct number of works."""
        continents = GlobalRegion.objects.filter(region_type=GlobalRegion.CONTINENT)

        for region in continents:
            with self.subTest(continent=region.name):
                slug = self.slugify(region.name)
                expected_count = EXPECTED_COUNTS.get(slug, 0)

                url = reverse("optimap:feed-continent-page", kwargs={"continent_slug": slug})
                response = self.client.get(url)

                # Page should load successfully
                self.assertEqual(response.status_code, 200, f"Continent page for {region.name} failed to load")

                # Check context variables
                self.assertIn("works", response.context)
                self.assertIn("region", response.context)
                self.assertEqual(response.context["region"].id, region.id)

                # Verify work count matches expected
                actual_works = response.context["works"]
                self.assertEqual(
                    len(actual_works),
                    expected_count,
                    f"Continent {region.name} ({slug}): expected {expected_count} works, got {len(actual_works)}",
                )

                # Verify the count is shown in the HTML (template uses |pluralize)
                if expected_count > 0:
                    expected_phrase = f"{expected_count} research work{'' if expected_count == 1 else 's'}"
                    self.assertContains(
                        response, expected_phrase, msg_prefix=f"Work count not displayed for {region.name}"
                    )

                    # Verify at least the first work title appears
                    self.assertContains(
                        response, actual_works[0].title, msg_prefix=f"First work title not found for {region.name}"
                    )

                    # Should NOT show empty message
                    self.assertNotContains(
                        response, "No works found", msg_prefix=f"{region.name} should not show empty message"
                    )
                else:
                    # Should show empty message
                    self.assertContains(
                        response, "No works found", msg_prefix=f"{region.name} should show empty message"
                    )

    def test_all_ocean_pages_display_correct_work_counts(self):
        """Test that all ocean feed pages display the correct number of works."""
        oceans = GlobalRegion.objects.filter(region_type=GlobalRegion.OCEAN)

        for region in oceans:
            with self.subTest(ocean=region.name):
                slug = self.slugify(region.name)
                expected_count = EXPECTED_COUNTS.get(slug, 0)

                url = reverse("optimap:feed-ocean-page", kwargs={"ocean_slug": slug})
                response = self.client.get(url)

                # Page should load successfully
                self.assertEqual(response.status_code, 200, f"Ocean page for {region.name} failed to load")

                # Check context variables
                self.assertIn("works", response.context)
                self.assertIn("region", response.context)
                self.assertEqual(response.context["region"].id, region.id)

                # Verify work count matches expected
                actual_works = response.context["works"]
                self.assertEqual(
                    len(actual_works),
                    expected_count,
                    f"Ocean {region.name} ({slug}): expected {expected_count} works, got {len(actual_works)}",
                )

                # Verify the count is shown in the HTML (template uses |pluralize)
                if expected_count > 0:
                    expected_phrase = f"{expected_count} research work{'' if expected_count == 1 else 's'}"
                    self.assertContains(
                        response, expected_phrase, msg_prefix=f"Work count not displayed for {region.name}"
                    )

                    # Verify at least the first work title appears
                    self.assertContains(
                        response, actual_works[0].title, msg_prefix=f"First work title not found for {region.name}"
                    )

                    # Should NOT show empty message
                    self.assertNotContains(
                        response, "No works found", msg_prefix=f"{region.name} should not show empty message"
                    )
                else:
                    # Should show empty message
                    self.assertContains(
                        response, "No works found", msg_prefix=f"{region.name} should show empty message"
                    )

    def test_continent_page_shows_region_metadata(self):
        """Test that continent pages show correct region metadata."""
        region = GlobalRegion.objects.filter(region_type=GlobalRegion.CONTINENT).first()
        slug = self.slugify(region.name)
        url = reverse("optimap:feed-continent-page", kwargs={"continent_slug": slug})
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)

        # Check region name appears in page
        self.assertContains(response, region.name)

        # Check region type appears
        self.assertContains(response, "Continent")

        # Check feed URLs are present
        self.assertIn("feed_urls", response.context)
        self.assertIn("georss", response.context["feed_urls"])
        self.assertIn("atom", response.context["feed_urls"])

    def test_ocean_page_shows_region_metadata(self):
        """Test that ocean pages show correct region metadata."""
        region = GlobalRegion.objects.filter(region_type=GlobalRegion.OCEAN).first()
        slug = self.slugify(region.name)
        url = reverse("optimap:feed-ocean-page", kwargs={"ocean_slug": slug})
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)

        # Check region name appears in page
        self.assertContains(response, region.name)

        # Check region type appears
        self.assertContains(response, "Ocean")

        # Check feed URLs are present
        self.assertIn("feed_urls", response.context)
        self.assertIn("georss", response.context["feed_urls"])
        self.assertIn("atom", response.context["feed_urls"])

    def test_feed_page_cache_refresh(self):
        """Test that ?now parameter forces cache refresh."""
        region = GlobalRegion.objects.filter(region_type=GlobalRegion.CONTINENT).first()
        slug = self.slugify(region.name)
        url = reverse("optimap:feed-continent-page", kwargs={"continent_slug": slug})

        # First request (no cache)
        response1 = self.client.get(url)
        self.assertEqual(response1.status_code, 200)

        # Second request (should be cached)
        response2 = self.client.get(url)
        self.assertEqual(response2.status_code, 200)

        # Third request with ?now (forces refresh)
        response3 = self.client.get(url + "?now")
        self.assertEqual(response3.status_code, 200)

    def test_invalid_continent_returns_404(self):
        """Test that invalid continent slug returns 404."""
        url = reverse("optimap:feed-continent-page", kwargs={"continent_slug": "invalid-continent"})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 404)

    def test_invalid_ocean_returns_404(self):
        """Test that invalid ocean slug returns 404."""
        url = reverse("optimap:feed-ocean-page", kwargs={"ocean_slug": "invalid-ocean"})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 404)


class GeometryTypeFeedTests(TestCase):
    """Explicit, named-work assertions per geometry type (issue #179).

    test_georss_feed_per_region above already verifies feed contents against
    a DB query for every region; these tests pin specific titles/geometry
    types so a spatial-filter regression points directly at the broken case.
    """

    fixtures = ["test_data_global_feeds"]

    @classmethod
    def setUpClass(cls):
        cls._regions_tmp = tempfile.mkdtemp(prefix="optimap_global_regions_")
        _install_global_region_fixtures(cls._regions_tmp)
        cls._settings_override = override_settings(GLOBAL_REGIONS_DATA_DIR=cls._regions_tmp)
        cls._settings_override.enable()
        super().setUpClass()

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        cls._settings_override.disable()
        shutil.rmtree(cls._regions_tmp, ignore_errors=True)

    @classmethod
    def setUpTestData(cls):
        call_command("flush", "--no-input")
        call_command("load_global_regions")
        call_command("loaddata", "test_data_global_feeds")

    def slugify(self, name):
        return name.lower().replace(" ", "-")

    def _continent_titles(self, slug):
        url = reverse("optimap:api-continent-georss", kwargs={"continent_slug": slug})
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200, f"{slug} GeoRSS feed failed")
        root = ET.fromstring(resp.content)
        return [item.find("title").text for item in root.findall(".//item")]

    def _ocean_titles(self, slug):
        url = reverse("optimap:api-ocean-georss", kwargs={"ocean_slug": slug})
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200, f"{slug} GeoRSS feed failed")
        root = ET.fromstring(resp.content)
        return [item.find("title").text for item in root.findall(".//item")]

    def test_point_work_in_correct_region_feed(self):
        """A POINT-geometry work appears in the feed for the region it falls in."""
        titles = self._continent_titles("africa")
        self.assertIn("Field Site: Central Africa", titles)

    def test_linestring_work_in_correct_region_feeds(self):
        """A LINESTRING-geometry work crossing two continents appears in both feeds."""
        title = "Migration Route: Africa to Europe"
        self.assertIn(title, self._continent_titles("africa"))
        self.assertIn(title, self._continent_titles("europe"))

    def test_multi_polygon_collection_in_both_continent_feeds(self):
        """GEOMETRYCOLLECTION(POLYGON, POLYGON) appears in feeds for both member polygons."""
        title = "Dual-Polygon Study: Europe and Asia"
        self.assertIn(title, self._continent_titles("europe"))
        self.assertIn(title, self._continent_titles("asia"))

    def test_multi_polygon_collection_in_both_ocean_feeds(self):
        """GEOMETRYCOLLECTION(POLYGON, POLYGON) appears in feeds for both member polygons."""
        title = "Dual-Polygon Study: North Atlantic and Arctic"
        self.assertIn(title, self._ocean_titles("north-atlantic-ocean"))
        self.assertIn(title, self._ocean_titles("arctic-ocean"))

    def test_multi_ocean_multipolygon_work_in_all_ocean_feeds(self):
        """A MULTIPOLYGON work spanning three oceans appears in all three feeds."""
        title = "Global Ocean Survey"
        self.assertIn(title, self._ocean_titles("south-atlantic-ocean"))
        self.assertIn(title, self._ocean_titles("indian-ocean"))
        self.assertIn(title, self._ocean_titles("south-pacific-ocean"))

    def test_ocean_continent_spanning_work(self):
        """A work whose polygon straddles an ocean and a continent appears in both feeds."""
        title = "Cross-Regional Study: North America-Atlantic"
        self.assertIn(title, self._continent_titles("north-america"))
        self.assertIn(title, self._ocean_titles("north-atlantic-ocean"))
