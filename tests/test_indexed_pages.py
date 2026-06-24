# SPDX-FileCopyrightText: 2026 OPTIMETA and KOMET projects <https://projects.tib.eu/komet>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests for the faceted permalink pages: /at/, /during/, /on/, /browse/ (#29)."""

import datetime

from django.contrib.gis.geos import GeometryCollection, MultiPolygon, Point, Polygon
from django.core.cache import cache
from django.test import Client, TestCase
from django.urls import reverse

from works.models import Country, Source, Work


def _square(cx, cy, d=1.0):
    return Polygon(((cx - d, cy - d), (cx + d, cy - d), (cx + d, cy + d), (cx - d, cy + d), (cx - d, cy - d)))


class PlacePageTests(TestCase):
    def setUp(self):
        self.client = Client()
        cache.clear()
        self.germany = Country.objects.create(
            name="Germany", iso_code="DE", continent="Europe", geom=MultiPolygon(_square(10, 51))
        )
        german = Work.objects.create(status="p", title="German study", geometry=GeometryCollection(Point(10, 51)))
        german.countries.add(self.germany)
        # No France Country row — the French study simply has no country link.
        Work.objects.create(status="p", title="French study")

    def test_country_page(self):
        resp = self.client.get(reverse("optimap:at-place", kwargs={"place_slug": "germany"}))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "German study")
        self.assertNotContains(resp, "French study")
        self.assertContains(resp, "facet-map")  # map above the list (a work has geometry)

    def test_no_map_when_no_geometry(self):
        # A country whose published works have no geometry shows no (empty) map.
        mali = Country.objects.create(
            name="Mali", iso_code="ML", continent="Africa", geom=MultiPolygon(_square(-4, 17))
        )
        Work.objects.create(status="p", title="Mali study").countries.add(mali)  # no geometry
        resp = self.client.get(reverse("optimap:at-place", kwargs={"place_slug": "mali"}))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Mali study")
        self.assertNotContains(resp, "facet-map")

    def test_country_outline_drawn_when_map_shown(self):
        # When the map renders (a work has geometry), the country outline is drawn
        # from the shared, browser-cached /api/v1/countries/ data.
        resp = self.client.get(reverse("optimap:at-place", kwargs={"place_slug": "germany"}))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'facetCountryIso = "DE"')
        self.assertContains(resp, "countries-cache.js")

    def test_unknown_place_404(self):
        resp = self.client.get("/at/atlantis/")
        self.assertEqual(resp.status_code, 404)

    def test_iso_code_redirects_to_name_slug(self):
        for code in ("DE", "de"):
            resp = self.client.get(f"/at/{code}/")
            self.assertEqual(resp.status_code, 301)
            self.assertEqual(resp["Location"], "/at/germany/")

    def test_country_wins_over_same_named_continent(self):
        """When a country and continent share a name (Australia), /at/<slug>
        shows the country (by Work.countries), so the count matches /countries."""
        from works.models import GlobalRegion

        GlobalRegion.objects.create(
            name="Australia",
            region_type=GlobalRegion.CONTINENT,
            source_url="https://example.org",
            license="x",
            geom=MultiPolygon(_square(134, -25, 20)),
        )
        australia = Country.objects.create(
            name="Australia", iso_code="AU", continent="Oceania", geom=MultiPolygon(_square(134, -25, 5))
        )
        # 2 works linked to AU; the continent polygon also covers a geometry-only
        # work that must NOT be counted on the country page.
        Work.objects.create(status="p", title="AU tagged").countries.add(australia)
        Work.objects.create(status="p", title="AU tagged 2").countries.add(australia)
        Work.objects.create(status="p", title="In-continent only", geometry=GeometryCollection(Point(134, -25)))
        cache.clear()
        resp = self.client.get("/at/australia/")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "AU tagged")
        self.assertNotContains(resp, "In-continent only")
        self.assertContains(resp, "2 works")  # matches the /countries chip count

    def test_flag_emoji_shown_and_xk_has_none(self):
        from works.views_indexed import _flag_emoji

        self.assertEqual(_flag_emoji("DE"), "\U0001f1e9\U0001f1ea")
        self.assertEqual(_flag_emoji("XK"), "")  # Kosovo: no flag emoji
        Country.objects.create(name="Kosovo", iso_code="XK", continent="Europe", geom=MultiPolygon(_square(21, 42)))
        cache.clear()
        resp = self.client.get(reverse("optimap:countries"))
        self.assertContains(resp, "\U0001f1e9\U0001f1ea")  # Germany flag present
        self.assertContains(resp, "Kosovo")  # listed without a flag

    def test_zero_work_country_not_clickable(self):
        Country.objects.create(name="Tuvalu", iso_code="TV", continent="Oceania", geom=MultiPolygon(_square(178, -8)))
        cache.clear()
        resp = self.client.get(reverse("optimap:countries"))
        self.assertContains(resp, "Tuvalu")
        self.assertNotContains(resp, "/at/tuvalu/")  # no link for 0-work country


class PlaceIndexTests(TestCase):
    def setUp(self):
        self.client = Client()
        cache.clear()
        Country.objects.create(name="Germany", iso_code="DE", continent="Europe", geom=MultiPolygon(_square(10, 51)))
        Country.objects.create(name="Kenya", iso_code="KE", continent="Africa", geom=MultiPolygon(_square(37, 0)))

    def test_at_index_points_to_countries(self):
        # /at/ is the umbrella index: it links to /countries/ rather than
        # duplicating the full country list.
        resp = self.client.get(reverse("optimap:at-index"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, reverse("optimap:countries"))

    def test_countries_overview_grouped_by_continent(self):
        resp = self.client.get(reverse("optimap:countries"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Europe")
        self.assertContains(resp, "Africa")
        self.assertContains(resp, "Germany")

    def test_continent_header_links_to_landing(self):
        from works.models import GlobalRegion

        GlobalRegion.objects.create(
            name="Europe",
            region_type=GlobalRegion.CONTINENT,
            source_url="https://example.org",
            license="x",
            geom=MultiPolygon(_square(10, 50, 30)),
        )
        cache.clear()
        resp = self.client.get(reverse("optimap:countries"))
        self.assertContains(resp, "/regions/continent/europe/")


class YearPageTests(TestCase):
    def setUp(self):
        self.client = Client()
        cache.clear()
        # Temporal coverage 2018–2020, but published in 2023 — proves data-year matching.
        self.covered = Work.objects.create(
            status="p",
            title="Spanning study",
            timeperiod_startdate=["2018-01-01"],
            timeperiod_enddate=["2020-12-31"],
            publicationDate=datetime.date(2023, 1, 1),
        )

    def test_matches_by_data_year_not_publication_date(self):
        resp = self.client.get(reverse("optimap:during-year", kwargs={"year": 2019}))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Spanning study")

    def test_publication_year_without_coverage_is_empty(self):
        cache.clear()
        resp = self.client.get(reverse("optimap:during-year", kwargs={"year": 2023}))
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, "Spanning study")

    def test_empty_in_range_year_is_200(self):
        cache.clear()
        resp = self.client.get(reverse("optimap:during-year", kwargs={"year": 1990}))
        self.assertEqual(resp.status_code, 200)

    def test_out_of_range_year_404(self):
        resp = self.client.get("/during/1700/")
        self.assertEqual(resp.status_code, 404)


class TopicPageTests(TestCase):
    def setUp(self):
        self.client = Client()
        cache.clear()
        Work.objects.create(status="p", title="RS work", topics=["Remote Sensing"])
        Work.objects.create(status="p", title="Hydro work", topics=["Hydrology"])

    def test_topic_page(self):
        resp = self.client.get(reverse("optimap:on-topic", kwargs={"topic_slug": "remote-sensing"}))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "RS work")
        self.assertNotContains(resp, "Hydro work")

    def test_unknown_topic_404(self):
        resp = self.client.get("/on/quantum-gravity/")
        self.assertEqual(resp.status_code, 404)


class BrowsePageTests(TestCase):
    def setUp(self):
        self.client = Client()
        cache.clear()
        self.source = Source.objects.create(name="Browsable Journal", url_field="https://e.org/oai")
        Work.objects.create(
            status="p",
            title="Browse work",
            source=self.source,
            topics=["Cartography"],
            timeperiod_startdate=["2021-01-01"],
            timeperiod_enddate=["2021-12-31"],
        )

    def test_browse_renders_sections(self):
        resp = self.client.get(reverse("optimap:browse"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Journals &amp; sources")
        self.assertContains(resp, "Browsable Journal")
        self.assertContains(resp, "Cartography")
        self.assertContains(resp, "2021")


class IndexedSitemapTests(TestCase):
    def setUp(self):
        cache.clear()
        self.source = Source.objects.create(name="Sitemap Source", url_field="https://e.org/oai")
        germany = Country.objects.create(name="Germany", iso_code="DE", geom=MultiPolygon(_square(10, 51)))
        work = Work.objects.create(
            status="p",
            title="Sitemap work",
            source=self.source,
            topics=["Geodesy"],
            geometry=GeometryCollection(Point(10, 51)),
            timeperiod_startdate=["2022-01-01"],
            timeperiod_enddate=["2022-12-31"],
        )
        work.countries.add(germany)

    def test_sitemaps_contain_new_facets(self):
        from optimap.sitemaps import (
            CountrySitemap,
            SourceFeedsSitemap,
            SourceIndexSitemap,
            TopicSitemap,
            YearSitemap,
        )

        self.assertTrue(any(c.iso_code == "DE" for c in CountrySitemap().items()))
        self.assertIn(2022, YearSitemap().items())
        self.assertIn("geodesy", TopicSitemap().items())
        self.assertTrue(any(s.slug == self.source.slug for s in SourceIndexSitemap().items()))
        self.assertTrue(any(item[0].slug == self.source.slug for item in SourceFeedsSitemap().items()))
