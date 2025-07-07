import json
from xml.etree import ElementTree as ET

from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from publications.models import Publication, GlobalRegion


class FeedByGeometryTests(TestCase):
    fixtures = ["test_data_global_feeds"]

    @classmethod
    def setUpTestData(cls):
        call_command("loaddata", "test_data_global_feeds", verbosity=0)

    def slugify(self, name):
        return name.lower().replace(" ", "-")

    def test_geojson_feed_per_region(self):
        for region in GlobalRegion.objects.all():
            url = (
                reverse("optimap:global_feed", kwargs={
                    "region_type": region.region_type,
                    "name": region.name,
                })
                + ".geojson"
            )
            resp = self.client.get(url)
            self.assertEqual(resp.status_code, 200,
                             f"{region.name} JSON feed failed")

            data = resp.json()
            expected_dois = set(
                Publication.objects
                .filter(
                    status="p",
                    geometry__isnull=False,
                    geometry__intersects=region.geom
                )
                .values_list("doi", flat=True)
            )
            returned_dois = {
                feat["properties"]["doi"]
                for feat in data.get("features", [])
            }
            self.assertSetEqual(
                returned_dois, expected_dois,
                f"GeoJSON feed for {region.name} returned {returned_dois!r}, expected {expected_dois!r}"
            )

    def test_georss_feed_per_region(self):
        for region in GlobalRegion.objects.all():
            slug = self.slugify(region.name)
            url = reverse("feed-georss-by-slug", kwargs={
                "geometry_slug": slug
            })
            resp = self.client.get(url)
            self.assertEqual(resp.status_code, 200,
                             f"{region.name} GeoRSS feed failed")

            root = ET.fromstring(resp.content)
            titles = [item.find("title").text
                      for item in root.findall(".//item")]

            expected_titles = list(
                Publication.objects
                .filter(
                    status="p",
                    geometry__isnull=False,
                    geometry__intersects=region.geom
                )
                .order_by("-creationDate")
                .values_list("title", flat=True)[:10]
            )

            self.assertCountEqual(
                titles, expected_titles,
                f"GeoRSS feed for {region.name} returned {titles!r}, expected {expected_titles!r}"
            )
