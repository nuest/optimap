import unittest
from django.test import TestCase
from django.urls import reverse
from publications.models import Publication
from django.contrib.gis.geos import Point, GeometryCollection

@unittest.skip("Enable after /article/<doi> landing page is implemented and routed.")
class ArticleLandingTests(TestCase):
    def setUp(self):
        self.pub = Publication.objects.create(
            title="Landing Test",
            doi="10.4242/landing-xyz",
            url="https://example.com/landing",
            status="p",
            geometry=GeometryCollection(Point(1,1)),
        )

    def test_article_landing_renders(self):
        url = reverse("optimap:article-landing", args=[self.pub.doi])
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Landing Test")
        self.assertContains(resp, "Incorrect information can be reported")

    def test_article_landing_404_for_unknown(self):
        url = reverse("optimap:article-landing", args=["10.9999/does-not-exist"])
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 404)
