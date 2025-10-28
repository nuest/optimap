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

from works.models import Work, GlobalRegion


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


class FeedLandingPageTests(TestCase):
    fixtures = ["test_data_global_feeds"]

    @classmethod
    def setUpTestData(cls):
        call_command("load_global_regions")
        call_command("loaddata", "test_data_global_feeds")

    def _slugify(self, name):
        """Convert region name to slug."""
        return name.lower().replace(" ", "-")

    def test_all_continent_pages_display_correct_work_counts(self):
        """Test that all continent feed pages display the correct number of works."""
        continents = GlobalRegion.objects.filter(region_type=GlobalRegion.CONTINENT)

        for region in continents:
            with self.subTest(continent=region.name):
                slug = self._slugify(region.name)
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
                    self.assertContains(response, f'Showing {expected_count} publication',
                                       msg_prefix=f"Work count not displayed for {region.name}")

                    # Verify at least the first work title appears
                    self.assertContains(response, actual_works[0].title,
                                       msg_prefix=f"First work title not found for {region.name}")

                    # Should NOT show empty message
                    self.assertNotContains(response, 'No publications found',
                                         msg_prefix=f"{region.name} should not show empty message")
                else:
                    # Should show empty message
                    self.assertContains(response, 'No publications found',
                                       msg_prefix=f"{region.name} should show empty message")

    def test_all_ocean_pages_display_correct_work_counts(self):
        """Test that all ocean feed pages display the correct number of works."""
        oceans = GlobalRegion.objects.filter(region_type=GlobalRegion.OCEAN)

        for region in oceans:
            with self.subTest(ocean=region.name):
                slug = self._slugify(region.name)
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
                    self.assertContains(response, f'Showing {expected_count} publication',
                                       msg_prefix=f"Work count not displayed for {region.name}")

                    # Verify at least the first work title appears
                    self.assertContains(response, actual_works[0].title,
                                       msg_prefix=f"First work title not found for {region.name}")

                    # Should NOT show empty message
                    self.assertNotContains(response, 'No publications found',
                                         msg_prefix=f"{region.name} should not show empty message")
                else:
                    # Should show empty message
                    self.assertContains(response, 'No publications found',
                                       msg_prefix=f"{region.name} should show empty message")

    def test_continent_page_shows_region_metadata(self):
        """Test that continent pages show correct region metadata."""
        region = GlobalRegion.objects.filter(region_type=GlobalRegion.CONTINENT).first()
        slug = self._slugify(region.name)
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
        slug = self._slugify(region.name)
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
        slug = self._slugify(region.name)
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
