
import os
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "optimap.settings")
import django
django.setup()

import json
from xml.etree import ElementTree as ET

from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from works.models import Work, GlobalRegion

NSPS = {"atom": "http://www.w3.org/2005/Atom"}

class GlobalRssTests(TestCase):
    fixtures = ["test_data_global_feeds"]

    @classmethod
    def setUpTestData(cls):
        call_command("load_global_regions")
        call_command("loaddata", "test_data_global_feeds")

    def slugify(self, name):
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
