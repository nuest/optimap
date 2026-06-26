# SPDX-FileCopyrightText: 2026 OPTIMETA and KOMET projects <https://projects.tib.eu/komet>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests for persisted Work.regions + the region backfill sweep.

Mirrors tests/test_work_countries.py — the region pipeline is the global-region
(continent + ocean) analogue of the country point-in-polygon join.
"""

from django.contrib.gis.geos import (
    GeometryCollection,
    LineString,
    MultiPolygon,
    Point,
    Polygon,
)
from django.core import mail
from django.test import TestCase, override_settings

from works.models import GlobalRegion, Work
from works.services.regions import regions_for_geometry
from works.tasks import backfill_work_regions

_LOCMEM_EMAIL = override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    ADMINS=[],  # suppress AdminEmailHandler noise in mail.outbox (e.g. empty-table warning)
)


def _box(minx, miny, maxx, maxy):
    return MultiPolygon(Polygon(((minx, miny), (maxx, miny), (maxx, maxy), (minx, maxy), (minx, miny))))


def _make_region(name, region_type, geom):
    return GlobalRegion.objects.create(
        name=name,
        region_type=region_type,
        source_url="https://example.org/regions",
        license="CC0",
        geom=geom,
    )


class RegionsForGeometryTests(TestCase):
    def setUp(self):
        # A "continent" box and an adjacent "ocean" box sharing the x=10 edge.
        self.land = _make_region("Testland", GlobalRegion.CONTINENT, _box(5, 47, 10, 55))
        self.sea = _make_region("Testsea", GlobalRegion.OCEAN, _box(10, 47, 20, 55))

    def test_single_region_point(self):
        rs = regions_for_geometry(GeometryCollection(Point(7, 51)))
        self.assertEqual([r.name for r in rs], ["Testland"])

    def test_multi_region_polygon(self):
        # A box straddling the shared edge intersects both regions.
        geom = GeometryCollection(Polygon(((8, 50), (12, 50), (12, 52), (8, 52), (8, 50))))
        self.assertEqual(sorted(r.name for r in regions_for_geometry(geom)), ["Testland", "Testsea"])

    def test_line_within_one_region(self):
        geom = GeometryCollection(LineString((6, 50), (9, 52)))
        self.assertEqual([r.name for r in regions_for_geometry(geom)], ["Testland"])

    def test_no_region_match(self):
        self.assertEqual(regions_for_geometry(GeometryCollection(Point(-30, 0))), [])

    def test_empty_geometry(self):
        self.assertEqual(regions_for_geometry(GeometryCollection()), [])
        self.assertEqual(regions_for_geometry(None), [])

    def test_invalid_geometry_is_repaired(self):
        # Self-intersecting "bow-tie" polygon inside Testland: feeding it raw to
        # GEOSIntersects raises TopologyException; MakeValid repairs it.
        bowtie = Polygon(((6, 48), (8, 50), (8, 48), (6, 50), (6, 48)))
        self.assertFalse(bowtie.valid)
        self.assertEqual([r.name for r in regions_for_geometry(GeometryCollection(bowtie))], ["Testland"])

    def test_no_buffer_snap(self):
        # 0.05° west of Testland's x=5 edge: countries snap here, regions do not.
        self.assertEqual(regions_for_geometry(GeometryCollection(Point(4.95, 51))), [])


@override_settings(GEOCODE_WORKS_ON_SAVE=True)
class AssignWorkRegionsSignalTests(TestCase):
    def setUp(self):
        self.land = _make_region("Testland", GlobalRegion.CONTINENT, _box(5, 47, 10, 55))

    def test_post_save_links_region(self):
        work = Work.objects.create(status="p", title="land work", geometry=GeometryCollection(Point(7, 51)))
        self.assertEqual([r.name for r in work.regions.all()], ["Testland"])

    def test_post_save_records_provenance(self):
        work = Work.objects.create(status="p", title="land work", geometry=GeometryCollection(Point(7, 51)))
        work.refresh_from_db()
        block = work.provenance["regions"]
        self.assertEqual(block["source"], "global_regions")
        self.assertEqual(block["method"], "intersects")
        self.assertEqual(block["regions"], [{"name": "Testland", "region_type": "Continent"}])

    @override_settings(GEOCODE_WORKS_ON_SAVE=False)
    def test_signal_inert_when_disabled(self):
        work = Work.objects.create(status="p", title="off", geometry=GeometryCollection(Point(7, 51)))
        self.assertEqual(list(work.regions.all()), [])


@_LOCMEM_EMAIL
@override_settings(GEOCODE_WORKS_ON_SAVE=False)
class BackfillWorkRegionsTests(TestCase):
    def setUp(self):
        from django.contrib.auth import get_user_model

        get_user_model().objects.create_user(username="staff", email="staff@example.org", password="x", is_staff=True)
        self.land = _make_region("Testland", GlobalRegion.CONTINENT, _box(5, 47, 10, 55))
        self.sea = _make_region("Testsea", GlobalRegion.OCEAN, _box(10, 47, 20, 55))
        mail.outbox.clear()

    def _work(self, geom):
        # GEOCODE_WORKS_ON_SAVE is off, so the post-save signal does not link.
        return Work.objects.create(status="p", title="w", geometry=geom)

    def test_backfill_links_single_and_multi(self):
        single = self._work(GeometryCollection(Point(7, 51)))
        multi = self._work(GeometryCollection(Polygon(((8, 50), (12, 50), (12, 52), (8, 52), (8, 50)))))
        nomatch = self._work(GeometryCollection(Point(-30, 0)))

        tally = backfill_work_regions()

        self.assertEqual([r.name for r in single.regions.all()], ["Testland"])
        self.assertEqual(sorted(r.name for r in multi.regions.all()), ["Testland", "Testsea"])
        self.assertEqual(list(nomatch.regions.all()), [])
        self.assertEqual(tally["updated"], 2)
        self.assertEqual(tally["multi_region"], 1)
        self.assertEqual(tally["no_match"], 1)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("Region backfill", mail.outbox[0].subject)
        self.assertIn("Works updated", mail.outbox[0].body)
        from django.conf import settings

        self.assertIn(settings.BASE_URL, mail.outbox[0].body)

    def test_no_email_on_noop_run(self):
        backfill_work_regions()
        self.assertEqual(len(mail.outbox), 0)

    def test_does_not_bump_last_update(self):
        work = self._work(GeometryCollection(Point(7, 51)))
        before = Work.objects.get(pk=work.pk).lastUpdate
        backfill_work_regions()
        self.assertEqual(Work.objects.get(pk=work.pk).lastUpdate, before)

    def test_skips_already_linked(self):
        work = self._work(GeometryCollection(Point(7, 51)))
        work.regions.add(self.land)
        mail.outbox.clear()
        tally = backfill_work_regions()
        self.assertEqual(tally["updated"], 0)
        self.assertEqual(len(mail.outbox), 0)

    def test_records_join_provenance(self):
        work = self._work(GeometryCollection(Point(7, 51)))
        backfill_work_regions()
        work.refresh_from_db()
        self.assertEqual(work.provenance["regions"]["method"], "intersects")
        self.assertEqual(work.provenance["regions"]["regions"], [{"name": "Testland", "region_type": "Continent"}])

    def test_empty_region_table_skips(self):
        GlobalRegion.objects.all().delete()
        self._work(GeometryCollection(Point(7, 51)))
        tally = backfill_work_regions()
        self.assertEqual(tally["updated"], 0)
        self.assertEqual([m.subject for m in mail.outbox], [])


@override_settings(GEOCODE_WORKS_ON_SAVE=True)
class RegionStatisticsAndFeedConsistencyTests(TestCase):
    """The divergence this change fixes: statistics by_continent/by_ocean and the
    region feed-page listing now agree, since both read the same Work.regions M2M."""

    def setUp(self):
        self.land = _make_region("Testland", GlobalRegion.CONTINENT, _box(5, 47, 10, 55))
        self.sea = _make_region("Testsea", GlobalRegion.OCEAN, _box(10, 47, 20, 55))

    def test_statistics_match_feed_listing(self):
        from works.utils.statistics import calculate_statistics
        from works.views_regions import _get_regional_publications

        # Published works in Testland; one needs a url to appear on the feed page.
        Work.objects.create(
            status="p", title="A", url="https://example.org/a", geometry=GeometryCollection(Point(6, 50))
        )
        Work.objects.create(
            status="p", title="B", url="https://example.org/b", geometry=GeometryCollection(Point(8, 52))
        )

        stats = calculate_statistics()
        land_count = next(e["count"] for e in stats["by_continent"] if e["name"] == "Testland")
        feed_works = _get_regional_publications(self.land)

        self.assertEqual(land_count, 2)
        self.assertEqual(land_count, len(feed_works))
        # Zero-count regions are still listed (parity with previous behaviour).
        self.assertEqual(next(e["count"] for e in stats["by_ocean"] if e["name"] == "Testsea"), 0)


@override_settings(GEOCODE_WORKS_ON_SAVE=True)
class WorkLandingPageRegionsTests(TestCase):
    """The landing page lists linked regions (between Authors and Countries),
    each name linking to the region feed page — mirroring the countries list."""

    def setUp(self):
        self.land = _make_region("Testland", GlobalRegion.CONTINENT, _box(5, 47, 10, 55))
        self.sea = _make_region("Testsea", GlobalRegion.OCEAN, _box(10, 47, 20, 55))

    def test_landing_page_lists_region_links(self):
        # A box straddling the shared edge links both regions via the post_save signal.
        work = Work.objects.create(
            status="p",
            title="Straddler",
            url="https://example.org/s",
            geometry=GeometryCollection(Polygon(((8, 50), (12, 50), (12, 52), (8, 52), (8, 50)))),
        )
        self.assertEqual(sorted(r.name for r in work.regions.all()), ["Testland", "Testsea"])

        html = self.client.get(f"/work/{work.id}/").content.decode()
        self.assertIn(">Regions:</strong>", html)
        self.assertIn(f'href="{self.land.get_absolute_url()}">Testland</a>', html)
        self.assertIn(f'href="{self.sea.get_absolute_url()}">Testsea</a>', html)

    def test_landing_page_uses_singular_region_label(self):
        work = Work.objects.create(
            status="p",
            title="Single",
            url="https://example.org/single",
            geometry=GeometryCollection(Point(7, 51)),
        )
        html = self.client.get(f"/work/{work.id}/").content.decode()
        self.assertIn(">Region:</strong>", html)
        self.assertNotIn(">Regions:</strong>", html)
