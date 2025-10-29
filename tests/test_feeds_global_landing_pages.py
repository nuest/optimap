"""
Tests for regional feed landing pages.

These tests verify that the feed landing pages correctly display
works filtered by region.
"""

import os
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "optimap.settings")
import django
django.setup()

from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

import json
from xml.etree import ElementTree as ET

from works.models import Work, GlobalRegion


NSPS = {"atom": "http://www.w3.org/2005/Atom"}


# Expected work counts per region based on test_data_global_feeds fixture
# These values are hardcoded from the actual fixture data to ensure tests
# verify the exact expected behavior
EXPECTED_COUNTS = {
    # Continents
    'africa': 15,
    'antarctica': 2,
    'asia': 23,
    'australia': 6,
    'europe': 17,
    'north-america': 14,
    'oceania': 5,
    'south-america': 8,
    # Oceans
    'arctic-ocean': 5,
    'indian-ocean': 11,
    'north-atlantic-ocean': 18,
    'north-pacific-ocean': 13,
    'south-atlantic-ocean': 10,
    'southern-ocean': 5,
    'south-pacific-ocean': 8,
}


class GlobalFeedsAndLandingPageTests(TestCase):
    fixtures = ["test_data_global_feeds"]

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
        self.assertEqual(len(regions), 15)

    def test_georss_feed_per_region(self):
        for region in GlobalRegion.objects.all():
            slug = self.slugify(region.name)
            # Use new API v1 endpoint based on region type
            if region.region_type == 'continent':
                url = reverse("optimap:api-continent-georss", kwargs={"continent_slug": slug})
            else:  # ocean
                url = reverse("optimap:api-ocean-georss", kwargs={"ocean_slug": slug})

            resp = self.client.get(url)
            self.assertEqual(resp.status_code, 200,
                             f"{region.name} GeoRSS feed failed")

            root = ET.fromstring(resp.content)
            titles = [item.find("title").text
                      for item in root.findall(".//item")]

            expected_titles = list(
                Work.objects
                .filter(
                    status="p",
                    geometry__isnull=False,
                    geometry__intersects=region.geom
                )
                .order_by("-creationDate")
                .values_list("title", flat=True)
            )

            self.assertCountEqual(
                titles, expected_titles,
                f"GeoRSS feed for {region.name} returned {titles!r}, expected {expected_titles!r}"
            )

    def test_geoatom_feed_australia(self):
        # Use new API v1 Atom endpoint
        url = reverse("optimap:api-continent-atom", kwargs={"continent_slug": "australia"})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        root = ET.fromstring(response.content)
        titles = [entry.find("atom:title", namespaces=NSPS).text
                    for entry in root.findall(".//atom:entry", namespaces=NSPS)]

        self.assertEqual(len(titles), 6, "Atom feed for Australia should return 6 entries")
        self.assertEqual(titles[0], "Migration Route: Asia to Australia", "Atom feed for Australia returned unexpected title")

    def test_georss_feed_south_atlantic(self):
        # Use new API v1 GeoRSS endpoint
        url = reverse("optimap:api-ocean-georss", kwargs={"ocean_slug": "south-atlantic-ocean"})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        root = ET.fromstring(response.content)
        titles = [item.find("title").text
                    for item in root.findall(".//item", namespaces=NSPS)]

        self.assertEqual(len(titles), 10, "GeoRSS feed for South Atlantic Ocean should return 10 entries")
        self.assertEqual(titles[0], "Marine Biology and Oceanography of the Southern Ocean", "GeoRSS feed for South Atlantic Ocean returned unexpected first title")
        self.assertEqual(titles[9], "Global Climate Network", "GeoRSS feed for South Atlantic Ocean returned unexpected last title")


    def test_all_continent_pages_display_correct_work_counts(self):
        """Test that all continent feed pages display the correct number of works."""
        continents = GlobalRegion.objects.filter(region_type=GlobalRegion.CONTINENT)

        for region in continents:
            with self.subTest(continent=region.name):
                slug = self.slugify(region.name)
                expected_count = EXPECTED_COUNTS.get(slug, 0)

                url = reverse('optimap:feed-continent-page', kwargs={'continent_slug': slug})
                response = self.client.get(url)

                # Page should load successfully
                self.assertEqual(response.status_code, 200,
                                f"Continent page for {region.name} failed to load")

                # Check context variables
                self.assertIn('works', response.context)
                self.assertIn('region', response.context)
                self.assertEqual(response.context['region'].id, region.id)

                # Verify work count matches expected
                actual_works = response.context['works']
                self.assertEqual(len(actual_works), expected_count,
                               f"Continent {region.name} ({slug}): expected {expected_count} works, got {len(actual_works)}")

                # Verify the count is shown in the HTML
                if expected_count > 0:
                    self.assertContains(response, f'{expected_count} research works',
                                       msg_prefix=f"Work count not displayed for {region.name}")

                    # Verify at least the first work title appears
                    self.assertContains(response, actual_works[0].title,
                                       msg_prefix=f"First work title not found for {region.name}")

                    # Should NOT show empty message
                    self.assertNotContains(response, 'No works found',
                                         msg_prefix=f"{region.name} should not show empty message")
                else:
                    # Should show empty message
                    self.assertContains(response, 'No works found',
                                       msg_prefix=f"{region.name} should show empty message")

    def test_all_ocean_pages_display_correct_work_counts(self):
        """Test that all ocean feed pages display the correct number of works."""
        oceans = GlobalRegion.objects.filter(region_type=GlobalRegion.OCEAN)

        for region in oceans:
            with self.subTest(ocean=region.name):
                slug = self.slugify(region.name)
                expected_count = EXPECTED_COUNTS.get(slug, 0)

                url = reverse('optimap:feed-ocean-page', kwargs={'ocean_slug': slug})
                response = self.client.get(url)

                # Page should load successfully
                self.assertEqual(response.status_code, 200,
                                f"Ocean page for {region.name} failed to load")

                # Check context variables
                self.assertIn('works', response.context)
                self.assertIn('region', response.context)
                self.assertEqual(response.context['region'].id, region.id)

                # Verify work count matches expected
                actual_works = response.context['works']
                self.assertEqual(len(actual_works), expected_count,
                               f"Ocean {region.name} ({slug}): expected {expected_count} works, got {len(actual_works)}")

                # Verify the count is shown in the HTML
                if expected_count > 0:
                    self.assertContains(response, f'{expected_count} research works',
                                       msg_prefix=f"Work count not displayed for {region.name}")

                    # Verify at least the first work title appears
                    self.assertContains(response, actual_works[0].title,
                                       msg_prefix=f"First work title not found for {region.name}")

                    # Should NOT show empty message
                    self.assertNotContains(response, 'No works found',
                                         msg_prefix=f"{region.name} should not show empty message")
                else:
                    # Should show empty message
                    self.assertContains(response, 'No works found',
                                       msg_prefix=f"{region.name} should show empty message")

    def test_continent_page_shows_region_metadata(self):
        """Test that continent pages show correct region metadata."""
        region = GlobalRegion.objects.filter(region_type=GlobalRegion.CONTINENT).first()
        slug = self.slugify(region.name)
        url = reverse('optimap:feed-continent-page', kwargs={'continent_slug': slug})
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)

        # Check region name appears in page
        self.assertContains(response, region.name)

        # Check region type appears
        self.assertContains(response, 'Continent')

        # Check feed URLs are present
        self.assertIn('feed_urls', response.context)
        self.assertIn('georss', response.context['feed_urls'])
        self.assertIn('atom', response.context['feed_urls'])

    def test_ocean_page_shows_region_metadata(self):
        """Test that ocean pages show correct region metadata."""
        region = GlobalRegion.objects.filter(region_type=GlobalRegion.OCEAN).first()
        slug = self.slugify(region.name)
        url = reverse('optimap:feed-ocean-page', kwargs={'ocean_slug': slug})
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)

        # Check region name appears in page
        self.assertContains(response, region.name)

        # Check region type appears
        self.assertContains(response, 'Ocean')

        # Check feed URLs are present
        self.assertIn('feed_urls', response.context)
        self.assertIn('georss', response.context['feed_urls'])
        self.assertIn('atom', response.context['feed_urls'])

    def test_feed_page_cache_refresh(self):
        """Test that ?now parameter forces cache refresh."""
        region = GlobalRegion.objects.filter(region_type=GlobalRegion.CONTINENT).first()
        slug = self.slugify(region.name)
        url = reverse('optimap:feed-continent-page', kwargs={'continent_slug': slug})

        # First request (no cache)
        response1 = self.client.get(url)
        self.assertEqual(response1.status_code, 200)

        # Second request (should be cached)
        response2 = self.client.get(url)
        self.assertEqual(response2.status_code, 200)

        # Third request with ?now (forces refresh)
        response3 = self.client.get(url + '?now')
        self.assertEqual(response3.status_code, 200)

    def test_invalid_continent_returns_404(self):
        """Test that invalid continent slug returns 404."""
        url = reverse('optimap:feed-continent-page', kwargs={'continent_slug': 'invalid-continent'})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 404)

    def test_invalid_ocean_returns_404(self):
        """Test that invalid ocean slug returns 404."""
        url = reverse('optimap:feed-ocean-page', kwargs={'ocean_slug': 'invalid-ocean'})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 404)
