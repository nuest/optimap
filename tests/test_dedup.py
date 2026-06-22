# SPDX-FileCopyrightText: 2026 OPTIMETA and KOMET projects <https://projects.tib.eu/komet>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests for automatic OpenAlex-driven deduplication (works/dedup.py)."""

from unittest import mock

from django.contrib.gis.geos import GeometryCollection, Point
from django.test import TestCase, override_settings
from django.urls import reverse

from works import dedup
from works.harvesting.openalex_locations import build_locations
from works.models import Work
from works.utils.identifiers import resolve_work_for_landing, resolve_work_identifier

OPENALEX_ID = "https://openalex.org/W123"
PUBLISHED_URL = "https://essd.example/article"
PREPRINT_URL = "https://eartharxiv.example/preprint"


def _openalex_payload():
    return {
        "id": OPENALEX_ID,
        "primary_location": {
            "landing_page_url": PUBLISHED_URL,
            "version": "publishedVersion",
            "is_oa": True,
            "license": "cc-by",
            "source": {"id": "https://openalex.org/S1", "display_name": "ESSD", "type": "journal"},
        },
        "locations": [
            {"landing_page_url": PUBLISHED_URL, "version": "publishedVersion"},
            {"landing_page_url": PREPRINT_URL, "version": "submittedVersion", "is_oa": True},
        ],
    }


def _make_work(*, doi, url, status="h", openalex_id=OPENALEX_ID, locations=None, geometry=None, openalex_ids=None):
    return Work.objects.create(
        title=f"Work {doi}",
        status=status,
        doi=doi,
        url=url,
        openalex_id=openalex_id,
        locations=locations if locations is not None else [],
        openalex_ids=openalex_ids or {},
        geometry=geometry if geometry is not None else GeometryCollection(),
    )


class BuildLocationsTests(TestCase):
    def test_normalises_and_dedupes(self):
        locs = build_locations(_openalex_payload())
        self.assertEqual(len(locs), 2)
        self.assertTrue(locs[0]["is_primary"])
        self.assertEqual(locs[0]["landing_page_url"], PUBLISHED_URL)
        self.assertFalse(locs[1]["is_primary"])
        self.assertTrue(all(loc["credit"] == "openalex" for loc in locs))

    def test_empty_payload(self):
        self.assertEqual(build_locations(None), [])
        self.assertEqual(build_locations({}), [])


class ReconcileTests(TestCase):
    def setUp(self):
        locs = build_locations(_openalex_payload())
        # Article matches the primary location; preprint matches the secondary one.
        self.article = _make_work(doi="10.5194/essd-1", url=PUBLISHED_URL, locations=locs)
        self.preprint = _make_work(doi="10.31223/preprint-1", url=PREPRINT_URL, locations=locs)

    def test_merge_picks_openalex_primary_as_canonical(self):
        dedup.reconcile(self.preprint)

        self.article.refresh_from_db()
        self.preprint.refresh_from_db()
        self.assertEqual(self.article.status, "h")  # canonical survives
        self.assertEqual(self.preprint.status, "r")  # tombstone
        self.assertEqual(self.preprint.provenance["redirect"]["canonical_work_id"], self.article.id)
        self.assertEqual(self.article.provenance["dedup"]["primary_basis"], "openalex_primary_location")
        self.assertIn(self.preprint.id, self.article.provenance["dedup"]["merged_work_ids"])

    def test_disabled_is_noop(self):
        with override_settings(OPTIMAP_DEDUP_AUTO_MERGE=False):
            dedup.reconcile(self.preprint)
        self.preprint.refresh_from_db()
        self.assertEqual(self.preprint.status, "h")

    def test_version_rank_fallback(self):
        # No location matches either work's url -> fall back to version rank.
        a = _make_work(doi="10.1/pub", url="https://x/pub", openalex_id="https://openalex.org/W9")
        b = _make_work(doi="10.1/pre", url="https://x/pre", openalex_id="https://openalex.org/W9")
        locs = [
            {
                "landing_page_url": "https://other/pub",
                "version": "publishedVersion",
                "doi": "10.1/pub",
                "credit": "openalex",
            },
            {
                "landing_page_url": "https://other/pre",
                "version": "submittedVersion",
                "doi": "10.1/pre",
                "credit": "openalex",
            },
        ]
        a.locations = locs
        a.save()
        dedup.reconcile(a)
        a.refresh_from_db()
        b.refresh_from_db()
        # 'a' holds the publishedVersion doi -> a is canonical.
        self.assertEqual(a.status, "h")
        self.assertEqual(b.status, "r")
        self.assertEqual(a.provenance["dedup"]["primary_basis"], "version_rank")

    def test_geometry_carryover_when_primary_empty(self):
        self.preprint.geometry = GeometryCollection(Point(1, 2))
        self.preprint.save()
        dedup.reconcile(self.preprint)
        self.article.refresh_from_db()
        self.assertFalse(self.article.geometry.empty)

    def test_geometry_conflict_recorded(self):
        self.article.geometry = GeometryCollection(Point(1, 2))
        self.article.save()
        self.preprint.geometry = GeometryCollection(Point(5, 6))
        self.preprint.save()
        dedup.reconcile(self.preprint)
        self.article.refresh_from_db()
        # Primary's geometry kept; the conflicting other recorded for audit.
        self.assertEqual(self.article.geometry[0].coords, (1, 2))
        conflicts = self.article.provenance.get("dedup_conflict", [])
        self.assertTrue(any(c["kind"] == "geometry" for c in conflicts))


class ResolutionRedirectTests(TestCase):
    def setUp(self):
        locs = build_locations(_openalex_payload())
        self.article = _make_work(
            doi="10.5194/essd-2",
            url=PUBLISHED_URL,
            status="p",
            locations=locs,
            openalex_ids={"pmid": "https://pubmed.ncbi.nlm.nih.gov/42", "doi": "https://doi.org/10.5194/essd-2"},
        )
        self.preprint = _make_work(doi="10.31223/preprint-2", url=PREPRINT_URL, status="p", locations=locs)
        dedup.reconcile(self.preprint)
        self.article.refresh_from_db()
        self.preprint.refresh_from_db()

    def test_redirected_doi_resolves_to_canonical(self):
        work, _ = resolve_work_identifier("10.31223/preprint-2")
        self.assertEqual(work.id, self.article.id)

    def test_landing_signals_redirect(self):
        work, _type, should_redirect = resolve_work_for_landing("10.31223/preprint-2")
        self.assertTrue(should_redirect)
        self.assertEqual(work.id, self.article.id)

    def test_openalex_external_id_resolves(self):
        work, id_type = resolve_work_identifier("https://pubmed.ncbi.nlm.nih.gov/42")
        self.assertEqual(work.id, self.article.id)
        self.assertEqual(id_type, "openalex_external_id")

    def test_landing_view_302(self):
        url = reverse("optimap:work-landing", args=["10.31223/preprint-2"])
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 302)
        self.assertIn(self.article.get_identifier(), resp["Location"])


class ApiVisibilityTests(TestCase):
    def setUp(self):
        locs = build_locations(_openalex_payload())
        self.article = _make_work(doi="10.5194/essd-3", url=PUBLISHED_URL, status="p", locations=locs)
        self.preprint = _make_work(doi="10.31223/preprint-3", url=PREPRINT_URL, status="p", locations=locs)
        dedup.reconcile(self.preprint)
        self.article.refresh_from_db()
        self.preprint.refresh_from_db()

    def test_list_excludes_redirected(self):
        resp = self.client.get("/api/v1/works/?format=json")
        self.assertEqual(resp.status_code, 200)
        ids = {f["id"] for f in resp.json()["results"]["features"]}
        self.assertIn(self.article.id, ids)
        self.assertNotIn(self.preprint.id, ids)

    def test_locations_exposed_and_credited(self):
        resp = self.client.get(f"/api/v1/works/{self.article.id}/?format=json")
        self.assertEqual(resp.status_code, 200)
        locs = resp.json()["properties"]["locations"]
        self.assertTrue(locs)
        self.assertEqual(locs[0]["credit"], "openalex")

    def test_detail_redirects_for_tombstone(self):
        resp = self.client.get(f"/api/v1/works/{self.preprint.id}/?format=json")
        self.assertEqual(resp.status_code, 302)


class UnmergeTests(TestCase):
    def test_unmerge_restores(self):
        locs = build_locations(_openalex_payload())
        article = _make_work(doi="10.5194/essd-4", url=PUBLISHED_URL, locations=locs)
        preprint = _make_work(doi="10.31223/preprint-4", url=PREPRINT_URL, locations=locs)
        dedup.reconcile(preprint)
        preprint.refresh_from_db()
        self.assertEqual(preprint.status, "r")

        dedup.unmerge(preprint)
        preprint.refresh_from_db()
        article.refresh_from_db()
        self.assertEqual(preprint.status, "h")
        self.assertNotIn("redirect", preprint.provenance)
        self.assertNotIn(preprint.id, article.provenance["dedup"]["merged_work_ids"])


class AdminUnmergeActionTests(TestCase):
    def test_admin_action_unmerges_redirected(self):
        from django.contrib.admin.sites import AdminSite
        from django.contrib.messages.storage.fallback import FallbackStorage
        from django.test import RequestFactory

        from works.admin import WorkAdmin

        locs = build_locations(_openalex_payload())
        article = _make_work(doi="10.5194/essd-6", url=PUBLISHED_URL, locations=locs)
        preprint = _make_work(doi="10.31223/preprint-6", url=PREPRINT_URL, locations=locs)
        dedup.reconcile(preprint)
        preprint.refresh_from_db()
        self.assertEqual(preprint.status, "r")

        request = RequestFactory().post("/admin/works/work/")
        setattr(request, "session", {})
        setattr(request, "_messages", FallbackStorage(request))
        admin = WorkAdmin(Work, AdminSite())
        admin.unmerge_works(request, Work.objects.filter(id=preprint.id))

        preprint.refresh_from_db()
        article.refresh_from_db()
        self.assertEqual(preprint.status, "h")
        self.assertNotIn(preprint.id, article.provenance["dedup"]["merged_work_ids"])


class SweepBackfillTests(TestCase):
    def test_sweep_backfills_locations_then_merges(self):
        # Two works sharing an openalex_id, neither has locations yet.
        a = _make_work(doi="10.5194/essd-5", url=PUBLISHED_URL)
        b = _make_work(doi="10.31223/preprint-5", url=PREPRINT_URL)

        with mock.patch("works.openalex_matcher.OpenAlexMatcher._make_request", return_value=_openalex_payload()):
            stats = dedup.sweep()

        self.assertGreaterEqual(stats["locations_filled"], 2)
        self.assertEqual(stats["groups_merged"], 1)
        a.refresh_from_db()
        b.refresh_from_db()
        # Locations backfilled on both; one becomes the tombstone.
        self.assertTrue(a.locations)
        statuses = {a.status, b.status}
        self.assertEqual(statuses, {"h", "r"})
