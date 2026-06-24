# SPDX-FileCopyrightText: 2026 OPTIMETA and KOMET projects <https://projects.tib.eu/komet>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests for multi-country support + the country backfill sweep (issue #261)."""

from django.contrib.gis.geos import (
    GeometryCollection,
    LineString,
    MultiPolygon,
    Point,
    Polygon,
)
from django.core import mail
from django.test import TestCase, override_settings

from works.models import Country, Work
from works.services.countries import countries_for_geometry
from works.tasks import backfill_work_countries

_LOCMEM_EMAIL = override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")


def _box(minx, miny, maxx, maxy):
    return MultiPolygon(Polygon(((minx, miny), (maxx, miny), (maxx, maxy), (minx, maxy), (minx, miny))))


class CountriesForGeometryTests(TestCase):
    def setUp(self):
        # Two adjacent boxes sharing the x=10 edge.
        self.de = Country.objects.create(name="Germany", iso_code="DE", geom=_box(5, 47, 10, 55))
        self.pl = Country.objects.create(name="Poland", iso_code="PL", geom=_box(10, 47, 20, 55))

    def test_single_country_point(self):
        cs = countries_for_geometry(GeometryCollection(Point(7, 51)))
        self.assertEqual([c.iso_code for c in cs], ["DE"])

    def test_multi_country_polygon(self):
        # A box straddling the shared edge intersects both countries.
        geom = GeometryCollection(Polygon(((8, 50), (12, 50), (12, 52), (8, 52), (8, 50))))
        self.assertEqual(sorted(c.iso_code for c in countries_for_geometry(geom)), ["DE", "PL"])

    def test_line_within_one_country(self):
        # A LineString fully inside Germany resolves to just DE.
        geom = GeometryCollection(LineString((6, 50), (9, 52)))
        self.assertEqual([c.iso_code for c in countries_for_geometry(geom)], ["DE"])

    def test_line_across_countries(self):
        # A LineString crossing the shared edge intersects both countries.
        geom = GeometryCollection(LineString((8, 51), (15, 51)))
        self.assertEqual(sorted(c.iso_code for c in countries_for_geometry(geom)), ["DE", "PL"])

    def test_multiple_polygons_within_one_country(self):
        # Two disjoint polygons, both inside Germany → DE once (no duplicates).
        geom = GeometryCollection(
            Polygon(((6, 48), (7, 48), (7, 49), (6, 49), (6, 48))),
            Polygon(((8, 53), (9, 53), (9, 54), (8, 54), (8, 53))),
        )
        self.assertEqual([c.iso_code for c in countries_for_geometry(geom)], ["DE"])

    def test_ocean_point_no_match(self):
        self.assertEqual(countries_for_geometry(GeometryCollection(Point(-30, 0))), [])

    def test_empty_geometry(self):
        self.assertEqual(countries_for_geometry(GeometryCollection()), [])
        self.assertEqual(countries_for_geometry(None), [])


@override_settings(GEOCODE_WORKS_ON_SAVE=True)
class AssignWorkCountriesSignalTests(TestCase):
    def setUp(self):
        self.de = Country.objects.create(name="Germany", iso_code="DE", geom=_box(5, 47, 10, 55))

    def test_post_save_links_country(self):
        work = Work.objects.create(status="p", title="DE work", geometry=GeometryCollection(Point(7, 51)))
        self.assertEqual([c.iso_code for c in work.countries.all()], ["DE"])

    @override_settings(GEOCODE_WORKS_ON_SAVE=False)
    def test_signal_inert_when_disabled(self):
        work = Work.objects.create(status="p", title="off", geometry=GeometryCollection(Point(7, 51)))
        self.assertEqual(list(work.countries.all()), [])


@_LOCMEM_EMAIL
@override_settings(GEOCODE_WORKS_ON_SAVE=False)
class BackfillWorkCountriesTests(TestCase):
    def setUp(self):
        from django.contrib.auth import get_user_model

        get_user_model().objects.create_user(username="staff", email="staff@example.org", password="x", is_staff=True)
        self.de = Country.objects.create(name="Germany", iso_code="DE", geom=_box(5, 47, 10, 55))
        self.pl = Country.objects.create(name="Poland", iso_code="PL", geom=_box(10, 47, 20, 55))
        mail.outbox.clear()

    def _work(self, geom):
        # GEOCODE_WORKS_ON_SAVE is off, so the post-save signal does not link.
        return Work.objects.create(status="p", title="w", geometry=geom)

    def test_backfill_links_single_and_multi(self):
        single = self._work(GeometryCollection(Point(7, 51)))
        multi = self._work(GeometryCollection(Polygon(((8, 50), (12, 50), (12, 52), (8, 52), (8, 50)))))
        ocean = self._work(GeometryCollection(Point(-30, 0)))

        tally = backfill_work_countries()

        self.assertEqual([c.iso_code for c in single.countries.all()], ["DE"])
        self.assertEqual(sorted(c.iso_code for c in multi.countries.all()), ["DE", "PL"])
        self.assertEqual(list(ocean.countries.all()), [])
        self.assertEqual(tally["updated"], 2)
        self.assertEqual(tally["multi_country"], 1)
        self.assertEqual(tally["no_match"], 1)
        # Email sent on change, with a substring of the summary.
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("Country backfill", mail.outbox[0].subject)
        self.assertIn("Works updated", mail.outbox[0].body)
        # Deployment URL lets staff tell the live server from a local demo.
        from django.conf import settings

        self.assertIn(settings.BASE_URL, mail.outbox[0].body)

    def test_backfill_handles_diverse_geometry_types(self):
        # The sweep must stay stable across the full diversity of geometries a
        # work can carry — points, lines, and multi-polygon collections, both
        # within and across country borders.
        line_within = self._work(GeometryCollection(LineString((6, 50), (9, 52))))
        line_across = self._work(GeometryCollection(LineString((8, 51), (15, 51))))
        multi_poly_within = self._work(
            GeometryCollection(
                Polygon(((6, 48), (7, 48), (7, 49), (6, 49), (6, 48))),
                Polygon(((8, 53), (9, 53), (9, 54), (8, 54), (8, 53))),
            )
        )

        tally = backfill_work_countries()

        self.assertEqual([c.iso_code for c in line_within.countries.all()], ["DE"])
        self.assertEqual(sorted(c.iso_code for c in line_across.countries.all()), ["DE", "PL"])
        self.assertEqual([c.iso_code for c in multi_poly_within.countries.all()], ["DE"])
        self.assertEqual(tally["updated"], 3)
        self.assertEqual(tally["multi_country"], 1)
        self.assertEqual(tally["no_match"], 0)

    def test_no_email_on_noop_run(self):
        # No works with geometry → nothing updated → no email.
        backfill_work_countries()
        self.assertEqual(len(mail.outbox), 0)

    def test_does_not_bump_last_update(self):
        work = self._work(GeometryCollection(Point(7, 51)))
        before = Work.objects.get(pk=work.pk).lastUpdate
        backfill_work_countries()
        self.assertEqual(Work.objects.get(pk=work.pk).lastUpdate, before)

    def test_skips_already_linked(self):
        work = self._work(GeometryCollection(Point(7, 51)))
        work.countries.add(self.de)
        mail.outbox.clear()
        tally = backfill_work_countries()
        self.assertEqual(tally["updated"], 0)
        self.assertEqual(len(mail.outbox), 0)

    def test_empty_country_table_skips(self):
        Country.objects.all().delete()
        self._work(GeometryCollection(Point(7, 51)))
        tally = backfill_work_countries()
        self.assertEqual(tally["updated"], 0)
        self.assertEqual(len(mail.outbox), 0)
