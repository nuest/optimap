from django.test import TestCase
from http import HTTPStatus

class SitemapTest(TestCase):
    def test_index(self):
        response = self.client.get("/sitemap.xml")
        self.assertEqual(response.status_code, HTTPStatus.OK)
        self.assertEqual(response["content-type"], "application/xml")

    def test_post(self):
        response = self.client.post("/sitemap.xml")

        self.assertEqual(response.status_code, HTTPStatus.METHOD_NOT_ALLOWED)

    def test_static(self):
        response = self.client.get("/sitemap-static.xml")
        self.assertEqual(response.status_code, HTTPStatus.OK)
        self.assertEqual(response["content-type"], "application/xml")

    def test_publications(self):
        response = self.client.get("/sitemap-publications.xml")
        self.assertEqual(response.status_code, HTTPStatus.OK)
        self.assertEqual(response["content-type"], "application/xml")
        # TODO test content
