# SPDX-FileCopyrightText: 2026 OPTIMETA and KOMET projects <https://projects.tib.eu/komet>
# SPDX-License-Identifier: GPL-3.0-or-later

"""SEO tests for issue #22.

Covers Open Graph / Twitter Card / schema.org JSON-LD / Google Scholar
``citation_*`` tags on the work landing page, ``WebSite`` / ``SearchAction``
JSON-LD on the homepage, ``CollectionPage`` JSON-LD on feed pages, and the
preview-image generator + cache invalidation. Avoids the network: the
preview renderer is monkey-patched to skip OSM tile fetches.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from unittest import mock

import django
from bs4 import BeautifulSoup
from django.test import Client, TestCase, override_settings
from django.urls import reverse

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'optimap.settings')
django.setup()

from django.contrib.gis.geos import GEOSGeometry, GeometryCollection
from works.models import Source, Work


def _polygon_collection(coords):
    geom = GEOSGeometry(json.dumps({"type": "Polygon", "coordinates": [coords]}), srid=4326)
    return GeometryCollection(geom, srid=4326)


def _make_published_work(**overrides) -> Work:
    src = Source.objects.create(
        name="SEO Test Journal",
        url_field="https://example.test/oai",
        homepage_url="https://example.test/",
        issn_l="1234-5678",
        harvest_interval_minutes=1440,
    )
    sulawesi = [[119.0, -5.7], [125.0, -5.7], [125.0, 1.7], [119.0, 1.7], [119.0, -5.7]]
    defaults = dict(
        title="Pollen, ash, and the Sulawesi caves: a chronology",
        abstract="A short abstract about Sulawesi cave sediments.",
        url="https://example.test/article/1",
        doi="10.1234/test.seo.1",
        source=src,
        status="p",
        geometry=_polygon_collection(sulawesi),
        timeperiod_startdate=[None],
        timeperiod_enddate=["2024-12-31"],
        authors=["Sontag-Gonzalez, Mariana", "Roberts, Richard G."],
        keywords=["Earth Sciences"],
        topics=["Geomagnetism and Paleomagnetism Studies"],
        publicationDate="2025-01-14",
    )
    defaults.update(overrides)
    return Work.objects.create(**defaults)


def _find_jsonld(soup: BeautifulSoup) -> list[dict]:
    blobs = []
    for tag in soup.find_all("script", attrs={"type": "application/ld+json"}):
        if tag.string and tag.string.strip():
            try:
                blobs.append(json.loads(tag.string))
            except json.JSONDecodeError:
                pass
    return blobs


class WorkLandingSEOTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.work = _make_published_work()
        self.url = reverse("optimap:work-landing", args=[self.work.get_identifier()])

    def test_open_graph_and_twitter_tags_present(self):
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)
        soup = BeautifulSoup(resp.content, "html.parser")
        for prop in ("og:title", "og:description", "og:url", "og:type", "og:site_name"):
            self.assertIsNotNone(
                soup.find("meta", attrs={"property": prop}),
                f"missing OG tag: {prop}",
            )
        for name in ("twitter:card", "twitter:title", "twitter:description"):
            self.assertIsNotNone(
                soup.find("meta", attrs={"name": name}),
                f"missing Twitter tag: {name}",
            )
        og_type = soup.find("meta", attrs={"property": "og:type"})
        self.assertEqual(og_type["content"], "article")

    def test_og_image_points_at_preview_endpoint(self):
        resp = self.client.get(self.url)
        soup = BeautifulSoup(resp.content, "html.parser")
        og_image = soup.find("meta", attrs={"property": "og:image"})
        self.assertIsNotNone(og_image, "og:image is required when geometry is present")
        preview_url = reverse("optimap:work-preview", args=[self.work.get_identifier()])
        self.assertIn(preview_url, og_image["content"])

    def test_og_image_omitted_for_work_without_geometry(self):
        # Q3 in the plan: works without geometry skip og:image entirely.
        no_geom = Work.objects.create(
            title="No-extent work",
            abstract="An abstract with no spatial coverage.",
            url="https://example.test/article/2",
            doi="10.1234/test.seo.2",
            source=self.work.source,
            status="p",
            geometry=GeometryCollection(),
            publicationDate="2025-01-14",
        )
        resp = self.client.get(reverse("optimap:work-landing", args=[no_geom.get_identifier()]))
        soup = BeautifulSoup(resp.content, "html.parser")
        self.assertIsNone(soup.find("meta", attrs={"property": "og:image"}))

    def test_canonical_link_present(self):
        resp = self.client.get(self.url)
        soup = BeautifulSoup(resp.content, "html.parser")
        link = soup.find("link", attrs={"rel": "canonical"})
        self.assertIsNotNone(link)
        self.assertIn(self.url, link["href"])

    def test_jsonld_scholarly_article(self):
        resp = self.client.get(self.url)
        soup = BeautifulSoup(resp.content, "html.parser")
        blobs = _find_jsonld(soup)
        article = next(
            (b for b in blobs if b.get("@type") == "ScholarlyArticle"),
            None,
        )
        self.assertIsNotNone(article, "ScholarlyArticle JSON-LD missing")
        self.assertEqual(article["name"], self.work.title)
        self.assertEqual(article.get("identifier"), f"doi:{self.work.doi}")
        self.assertEqual(article["sameAs"], f"https://doi.org/{self.work.doi}")
        self.assertEqual(len(article["author"]), 2)
        # spatialCoverage should mirror the input geometry — full circle with what
        # we *consume* from harvested Janeway pages. Work.geometry stores
        # everything as a GeometryCollection wrapping the actual shape, so the
        # JSON-LD reflects that wrapping.
        self.assertEqual(article["spatialCoverage"]["@type"], "Place")
        self.assertEqual(article["spatialCoverage"]["geo"]["type"], "GeometryCollection")
        self.assertEqual(
            article["spatialCoverage"]["geo"]["geometries"][0]["type"], "Polygon"
        )
        # temporalCoverage with open-start interval, matching ISO 8601 "../end".
        self.assertEqual(article["temporalCoverage"], "../2024-12-31")
        # publisher derived from work.source.
        self.assertEqual(article["publisher"]["@type"], "Organization")
        self.assertEqual(article["publisher"]["name"], "SEO Test Journal")

    def test_citation_meta_tags(self):
        resp = self.client.get(self.url)
        soup = BeautifulSoup(resp.content, "html.parser")
        # citation_title, citation_doi, citation_journal_title, citation_publication_date,
        # citation_abstract_html_url, citation_issn — all expected on a published work.
        for name in (
            "citation_title",
            "citation_doi",
            "citation_journal_title",
            "citation_publication_date",
            "citation_abstract_html_url",
            "citation_issn",
        ):
            self.assertIsNotNone(
                soup.find("meta", attrs={"name": name}),
                f"missing citation_* tag: {name}",
            )
        # One citation_author per author, in order.
        authors = [
            t["content"] for t in soup.find_all("meta", attrs={"name": "citation_author"})
        ]
        self.assertEqual(len(authors), 2)
        self.assertEqual(authors[0], "Mariana Sontag-Gonzalez")

    def test_unpublished_work_returns_404(self):
        # Sanity: SEO context must not leak unpublished works to anonymous users.
        unpublished = Work.objects.create(
            title="Draft", source=self.work.source, status="d",
            geometry=GeometryCollection(),
        )
        resp = self.client.get(reverse("optimap:work-landing", args=[unpublished.get_identifier()]))
        self.assertEqual(resp.status_code, 404)


class HomepageSEOTests(TestCase):
    def test_homepage_jsonld_website_with_searchaction(self):
        resp = self.client.get(reverse("optimap:main"))
        self.assertEqual(resp.status_code, 200)
        soup = BeautifulSoup(resp.content, "html.parser")
        blobs = _find_jsonld(soup)
        site = next((b for b in blobs if b.get("@type") == "WebSite"), None)
        self.assertIsNotNone(site, "WebSite JSON-LD missing on homepage")
        self.assertIn("potentialAction", site)
        self.assertEqual(site["potentialAction"]["@type"], "SearchAction")


class WorkPreviewImageTests(TestCase):
    """The renderer fetches OSM tiles, so we patch ``StaticMap.render`` and
    just exercise our own composition / branding / cache-invalidation logic."""

    def setUp(self):
        self.client = Client()
        self.work = _make_published_work(doi="10.1234/test.seo.preview")
        self.preview_url = reverse(
            "optimap:work-preview", args=[self.work.get_identifier()]
        )

    @staticmethod
    def _fake_tile_image(*args, **kwargs):
        from PIL import Image

        return Image.new("RGB", (1200, 630), color=(200, 220, 240))

    def test_preview_endpoint_serves_png(self):
        # Patch staticmap so no network call is made.
        from PIL import Image as _Image
        with mock.patch("works.services.preview_image.StaticMap") as SM:
            instance = SM.return_value
            instance.render.return_value = _Image.new("RGB", (1200, 630), color=(200, 220, 240))
            resp = self.client.get(self.preview_url)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["Content-Type"], "image/png")
        self.assertIn("max-age=", resp.get("Cache-Control", ""))
        # Verify the body is actually a PNG with the expected dimensions.
        from PIL import Image
        from io import BytesIO
        buf = BytesIO(b"".join(resp.streaming_content))
        img = Image.open(buf)
        self.assertEqual(img.size, (1200, 630))

    def test_preview_404_for_work_without_geometry(self):
        no_geom = Work.objects.create(
            title="No-extent",
            doi="10.1234/test.seo.preview-noextent",
            source=self.work.source,
            status="p",
            geometry=GeometryCollection(),
        )
        url = reverse("optimap:work-preview", args=[no_geom.get_identifier()])
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 404)

    def test_post_save_invalidates_cached_preview(self):
        from works.services.preview_image import cache_path_for, invalidate_preview

        path = cache_path_for(self.work)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"old preview bytes")
        self.assertTrue(path.exists())
        # Saving the work should fire the post_save signal and unlink the cache.
        self.work.title = self.work.title + " (edited)"
        self.work.save()
        self.assertFalse(path.exists(),
                         "post_save signal must invalidate the cached preview")


class FeedPageSEOTests(TestCase):
    """``CollectionPage`` JSON-LD on the regional feed pages."""

    @classmethod
    def setUpTestData(cls):
        # Seed a minimal Africa GlobalRegion so we don't depend on the
        # network-fetching ``load_global_regions`` command in the test DB.
        # The geometry is just a coarse bbox over Africa — good enough for
        # the route to resolve and the SEO context to assemble.
        from works.models import GlobalRegion
        africa_geojson = {
            "type": "MultiPolygon",
            "coordinates": [[[
                [-20.0, -36.0], [55.0, -36.0], [55.0, 38.0],
                [-20.0, 38.0], [-20.0, -36.0],
            ]]],
        }
        cls.africa = GlobalRegion.objects.create(
            name="Africa",
            region_type=GlobalRegion.CONTINENT,
            geom=GEOSGeometry(json.dumps(africa_geojson), srid=4326),
        )

    def test_continent_feed_page_emits_collectionpage(self):
        from django.core.cache import cache
        cache.clear()  # the feed page caches by slug; flush so we don't read stale
        resp = self.client.get("/feeds/continent/africa/")
        self.assertEqual(resp.status_code, 200)
        soup = BeautifulSoup(resp.content, "html.parser")
        blobs = _find_jsonld(soup)
        coll = next((b for b in blobs if b.get("@type") == "CollectionPage"), None)
        self.assertIsNotNone(coll, "CollectionPage JSON-LD missing on feed page")
        self.assertEqual(coll["about"]["@type"], "Place")
        self.assertEqual(coll["about"]["name"], "Africa")
        # Bounding box should round-trip from the GlobalRegion geometry.
        self.assertIn("box", coll["about"]["geo"])
