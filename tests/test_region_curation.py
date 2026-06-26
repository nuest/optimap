# SPDX-FileCopyrightText: 2026 OPTIMETA and KOMET projects <https://projects.tib.eu/komet>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Staff region-curation section on /regions (mirrors tests/test_country_curation.py)."""

import json
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.gis.geos import GeometryCollection, MultiPolygon, Point, Polygon
from django.test import TestCase, override_settings
from django.urls import reverse

from works.models import GlobalRegion, Work
from works.tasks import backfill_work_regions
from works.views_regions import unmatched_regions_qs

_LOCMEM_EMAIL = override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    ADMINS=[],
)


def _box(minx, miny, maxx, maxy):
    return MultiPolygon(Polygon(((minx, miny), (maxx, miny), (maxx, maxy), (minx, maxy), (minx, miny))))


def _make_region(name, region_type, geom):
    return GlobalRegion.objects.create(
        name=name, region_type=region_type, source_url="https://example.org/r", license="CC0", geom=geom
    )


class _Base(TestCase):
    def setUp(self):
        User = get_user_model()
        self.staff = User.objects.create_user(username="staff", email="staff@example.org", password="x", is_staff=True)
        self.user = User.objects.create_user(username="joe", email="joe@example.org", password="x")
        self.land = _make_region("Testland", GlobalRegion.CONTINENT, _box(5, 47, 10, 55))
        self.sea = _make_region("Testsea", GlobalRegion.OCEAN, _box(10, 47, 20, 55))

    def _unmatched_work(self, **kw):
        # GEOCODE_WORKS_ON_SAVE defaults off in tests; the point is outside every
        # region box, so even if it were on the work would still not match.
        return Work.objects.create(status="p", title="w", geometry=GeometryCollection(Point(-30, 0)), **kw)


class GatingTests(_Base):
    def test_curation_section_staff_only(self):
        url = reverse("optimap:feeds")
        self.assertNotContains(self.client.get(url), "Curation: works without a region")
        self.client.force_login(self.user)
        self.assertNotContains(self.client.get(url), "Curation: works without a region")
        self.client.force_login(self.staff)
        self.assertContains(self.client.get(url), "Curation: works without a region")

    def test_endpoints_reject_non_staff(self):
        work = self._unmatched_work()
        set_url = reverse("optimap:set-work-region", args=[work.id])
        backfill_url = reverse("optimap:trigger-region-backfill")
        for url in (set_url, backfill_url):
            self.assertNotEqual(self.client.post(url).status_code, 200)  # anonymous → redirect
        self.client.force_login(self.user)
        for url in (set_url, backfill_url):
            self.assertNotEqual(self.client.post(url).status_code, 200)


class UnmatchedQuerysetTests(_Base):
    def test_lists_geometry_without_region(self):
        work = self._unmatched_work()
        self.assertIn(work, list(unmatched_regions_qs()))

    def test_excludes_no_geometry(self):
        Work.objects.create(status="p", title="ng")
        self.assertEqual(list(unmatched_regions_qs()), [])

    def test_excludes_manual_decision(self):
        work = self._unmatched_work()
        work.regions.add(self.land)
        # Assigned works leave the list because they now have a region anyway.
        self.assertNotIn(work, list(unmatched_regions_qs()))


class AssignAndExcludeTests(_Base):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.staff)
        self.work = self._unmatched_work()
        self.url = reverse("optimap:set-work-region", args=[self.work.id])

    def _post(self, payload):
        return self.client.post(self.url, data=json.dumps(payload), content_type="application/json")

    def test_assign_region(self):
        resp = self._post({"region_id": self.land.id})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual([r.name for r in self.work.regions.all()], ["Testland"])
        self.work.refresh_from_db()
        block = self.work.provenance["regions"]
        self.assertEqual(block["source"], "manual")
        self.assertEqual(block["method"], "curator_assigned")
        self.assertEqual(block["regions"], [{"name": "Testland", "region_type": "Continent"}])
        self.assertEqual(block["decided_by"], self.staff.id)
        events = self.work.provenance["events"]
        self.assertEqual(events[-1]["type"], "region_curation")
        self.assertEqual(events[-1]["decision"], "assigned")
        self.assertEqual(events[-1]["region"], "Testland")

    def test_assign_is_additive(self):
        self._post({"region_id": self.land.id})
        self._post({"region_id": self.sea.id})
        self.assertEqual(sorted(r.name for r in self.work.regions.all()), ["Testland", "Testsea"])

    def test_assign_unknown_region_rejected(self):
        self.assertEqual(self._post({"region_id": 999999}).status_code, 400)

    def test_assign_non_numeric_region_rejected(self):
        # A malformed id must yield 400, not a 500 from the int-coercion ValueError.
        self.assertEqual(self._post({"region_id": "not-a-number"}).status_code, 400)

    def test_exclude_records_manual_block_with_no_regions(self):
        resp = self._post({"exclude": True})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(list(self.work.regions.all()), [])
        self.work.refresh_from_db()
        self.assertEqual(self.work.provenance["regions"]["method"], "curator_excluded")
        self.assertEqual(self.work.provenance["regions"]["regions"], [])

    def test_excluded_work_drops_from_unmatched_list(self):
        self._post({"exclude": True})
        self.assertNotIn(self.work, list(unmatched_regions_qs()))
        resp = self.client.get(reverse("optimap:feeds"))
        self.assertEqual(resp.context["page_obj"].paginator.count, 0)

    def test_assigned_work_drops_from_unmatched_list(self):
        self._post({"region_id": self.land.id})
        resp = self.client.get(reverse("optimap:feeds"))
        self.assertEqual(resp.context["page_obj"].paginator.count, 0)


@_LOCMEM_EMAIL
class BackfillSkipsManualTests(_Base):
    def test_excluded_work_skipped_by_backfill(self):
        # A work over Testland that a curator excluded must NOT be re-matched.
        work = Work.objects.create(status="p", title="ex", geometry=GeometryCollection(Point(7, 51)))
        self.client.force_login(self.staff)
        self.client.post(
            reverse("optimap:set-work-region", args=[work.id]),
            data=json.dumps({"exclude": True}),
            content_type="application/json",
        )
        backfill_work_regions()
        self.assertEqual(list(work.regions.all()), [])


class BackfillButtonTests(_Base):
    def test_returns_task_id(self):
        self.client.force_login(self.staff)
        with patch("works.views_regions.async_task", return_value="deadbeef") as mock:
            resp = self.client.post(reverse("optimap:trigger-region-backfill"))
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["task_id"], "deadbeef")
        self.assertTrue(data["task_name"])
        mock.assert_called_once_with("works.tasks.backfill_work_regions", trigger_source="manual")


@override_settings(GEOCODE_WORKS_ON_SAVE=True)
class SignalPreservationTests(_Base):
    def test_manual_decision_sticky_on_unrelated_save(self):
        work = Work.objects.create(status="p", title="m", geometry=GeometryCollection(Point(7, 51)))
        self.client.force_login(self.staff)
        # Curator excludes it (even though it matches Testland).
        self.client.post(
            reverse("optimap:set-work-region", args=[work.id]),
            data=json.dumps({"exclude": True}),
            content_type="application/json",
        )
        work.refresh_from_db()
        work.title = "renamed"
        work.save()
        self.assertEqual(list(work.regions.all()), [])

    def test_geometry_change_voids_manual_decision(self):
        # Manually assign Testland while geometry is in the ocean gap (no match).
        work = Work.objects.create(status="p", title="g", geometry=GeometryCollection(Point(-30, 0)))
        self.client.force_login(self.staff)
        self.client.post(
            reverse("optimap:set-work-region", args=[work.id]),
            data=json.dumps({"region_id": self.land.id}),
            content_type="application/json",
        )
        # Move the geometry into Testland — the automated join re-runs.
        work.refresh_from_db()
        work.geometry = GeometryCollection(Point(8, 52))
        work.save()
        work.refresh_from_db()
        self.assertEqual([r.name for r in work.regions.all()], ["Testland"])
        self.assertEqual(work.provenance["regions"]["source"], "global_regions")

    def test_geometry_change_to_gap_clears_manual_block(self):
        work = Work.objects.create(status="p", title="o", geometry=GeometryCollection(Point(7, 51)))
        self.client.force_login(self.staff)
        self.client.post(
            reverse("optimap:set-work-region", args=[work.id]),
            data=json.dumps({"exclude": True}),
            content_type="application/json",
        )
        work.refresh_from_db()
        work.geometry = GeometryCollection(Point(-30, 0))  # gap → no match
        work.save()
        work.refresh_from_db()
        self.assertEqual(list(work.regions.all()), [])
        self.assertIsNone(work.provenance.get("regions"))
