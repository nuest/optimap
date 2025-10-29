import unittest
import django
from django.test import TestCase
from django.urls import reverse
from works.models import Work
from django.contrib.gis.geos import Point, GeometryCollection

@unittest.skip("Enable after /article/<doi> landing page is implemented and routed.")
class ArticleLandingTests(TestCase):
    def setUp(self):
        self.pub_with_geom = Work.objects.create(
            title="With Geom",
            doi="10.9999/with-geom",
            status="p",
            geometry=GeometryCollection(Point(7.5, 51.9)),
        )
        self.pub_no_geom = Work.objects.create(
            title="No Geom",
            doi="10.9999/no-geom",
            status="p",
            geometry=None,
        )

    def test_page_renders_with_map_when_geometry_present(self):
        url = reverse("optimap:work-landing", args=[self.pub_with_geom.doi])
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        # feature_json is provided
        self.assertIn("feature_json", resp.context)
        self.assertIsNotNone(resp.context["feature_json"])
        # mini-map div present
        self.assertContains(resp, 'id="mini-map"', count=1)

    def test_page_hides_map_when_no_geometry(self):
        url = reverse("optimap:work-landing", args=[self.pub_no_geom.doi])
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        # feature_json omitted or None
        self.assertTrue("feature_json" in resp.context)
        self.assertIsNone(resp.context["feature_json"])
        # no map container
        self.assertNotContains(resp, 'id="mini-map"')

    def test_unknown_doi_returns_404(self):
            url = reverse("optimap:work-landing", args=["10.9999/missing"])
            self.assertEqual(self.client.get(url).status_code, 404)
    
    class ArticleLandingTests(TestCase):
        def setUp(self):
            self.pub_with_geom = Work.objects.create(
                title="With Geom",
                doi="10.9999/with-geom",
                status="p",
                geometry=GeometryCollection(Point(7.5, 51.9)),
            )
            self.pub_no_geom = Work.objects.create(
                title="No Geom",
                doi="10.9999/no-geom",
                status="p",
                geometry=None,
            )
    
        def test_page_renders_with_map_when_geometry_present(self):
            url = reverse("optimap:work-landing", args=[self.pub_with_geom.doi])
            resp = self.client.get(url)
            self.assertEqual(resp.status_code, 200)
            # feature_json is provided
            self.assertIn("feature_json", resp.context)
            self.assertIsNotNone(resp.context["feature_json"])
            # mini-map div present
            self.assertContains(resp, 'id="mini-map"', count=1)
    
        def test_page_hides_map_when_no_geometry(self):
            url = reverse("optimap:work-landing", args=[self.pub_no_geom.doi])
            resp = self.client.get(url)
            self.assertEqual(resp.status_code, 200)
            # feature_json omitted or None
            self.assertTrue("feature_json" in resp.context)
            self.assertIsNone(resp.context["feature_json"])
            # no map container
            self.assertNotContains(resp, 'id="mini-map"')
    
        def test_unknown_doi_returns_404(self):
            url = reverse("optimap:work-landing", args=["10.9999/missing"])
            self.assertEqual(self.client.get(url).status_code, 404)