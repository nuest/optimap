# SPDX-FileCopyrightText: 2026 OPTIMETA and KOMET projects <https://projects.tib.eu/komet>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests for the contribute-by-DOI feature.

Covers:
- the ``normalize_doi`` helper,
- the single-DOI Crossref harvester ``harvest_crossref_doi`` (with OpenAlex /
  OpenAIRE enrichment mocked offline),
- the ``POST /api/v1/works/contribute-doi/`` endpoint (auth, validation,
  existing-vs-created, provenance + recognition-board row),
- the ``contributed_dois`` statistic.
"""

import os

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "optimap.settings")
django.setup()

from unittest.mock import patch

import requests
import responses
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings, tag

from works.harvesting.crossref import get_user_contributions_source, harvest_crossref_doi
from works.models import Contribution, Work
from works.utils.identifiers import normalize_doi

User = get_user_model()

CONTRIBUTE_URL = "/api/v1/works/contribute-doi/"

_CACHES = {
    "default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"},
    "memory": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"},
    "dummy": {"BACKEND": "django.core.cache.backends.dummy.DummyCache"},
}


def _crossref_single(doi="10.1234/abc123", **overrides):
    """A minimal single-DOI Crossref response body ({"message": {...}})."""
    message = {
        "DOI": doi,
        "URL": f"https://doi.org/{doi}",
        "title": ["A contributed work"],
        "abstract": "<jats:p>Some abstract.</jats:p>",
        "published": {"date-parts": [[2024, 5, 1]]},
        "author": [{"given": "Ada", "family": "Lovelace"}],
    }
    message.update(overrides)
    return {"message": message}


class NormalizeDoiTests(TestCase):
    def test_bare_doi(self):
        self.assertEqual(normalize_doi("10.5194/gi-9-219-2020"), "10.5194/gi-9-219-2020")

    def test_doi_url(self):
        self.assertEqual(normalize_doi("https://doi.org/10.5194/example"), "10.5194/example")

    def test_dx_and_scheme_prefixes(self):
        self.assertEqual(normalize_doi("http://dx.doi.org/10.1234/x"), "10.1234/x")
        self.assertEqual(normalize_doi("doi:10.1234/x"), "10.1234/x")

    def test_whitespace_trimmed(self):
        self.assertEqual(normalize_doi("  10.1234/x  "), "10.1234/x")

    def test_case_of_body_preserved(self):
        self.assertEqual(normalize_doi("https://doi.org/10.1234/AbC"), "10.1234/AbC")

    def test_invalid_returns_none(self):
        for bad in ["", None, "not a doi", "10.x/y", "hello/world", "https://example.org/foo"]:
            self.assertIsNone(normalize_doi(bad), bad)


@override_settings(CACHES=_CACHES)
class HarvestCrossrefDoiTests(TestCase):
    def setUp(self):
        cache.clear()
        oa = patch("works.harvesting.crossref.build_openalex_fields", return_value=({}, {}))
        self.mock_oa = oa.start()
        self.addCleanup(oa.stop)
        oaire = patch("works.harvesting.crossref.enrich_work_from_openaire", return_value=None)
        self.mock_oaire = oaire.start()
        self.addCleanup(oaire.stop)
        # Avoid hitting publisher landing pages for abstracts.
        abstr = patch("works.harvesting.crossref.fetch_copernicus_abstract", return_value=None)
        abstr.start()
        self.addCleanup(abstr.stop)

    @responses.activate
    def test_creates_work_attached_to_user_contributions_source(self):
        responses.add(
            responses.GET,
            "https://api.crossref.org/works/10.1234/abc123",
            json=_crossref_single("10.1234/abc123"),
            status=200,
        )
        work, action = harvest_crossref_doi("10.1234/abc123")
        self.assertEqual(action, "created")
        self.assertEqual(work.status, "h")
        self.assertEqual(work.doi, "10.1234/abc123")
        source = get_user_contributions_source()
        self.assertEqual(work.source_id, source.id)
        self.assertIn(source.collection_id, work.collections.values_list("id", flat=True))
        self.mock_oaire.assert_called_once()

    @responses.activate
    def test_existing_doi_returns_exists(self):
        Work.objects.create(title="Existing", doi="10.1234/dup", status="h")
        responses.add(
            responses.GET,
            "https://api.crossref.org/works/10.1234/dup",
            json=_crossref_single("10.1234/dup"),
            status=200,
        )
        work, action = harvest_crossref_doi("10.1234/dup")
        self.assertEqual(action, "exists")

    @responses.activate
    def test_unknown_doi_returns_not_found(self):
        responses.add(
            responses.GET,
            "https://api.crossref.org/works/10.1234/missing",
            status=404,
        )
        work, action = harvest_crossref_doi("10.1234/missing")
        self.assertIsNone(work)
        self.assertEqual(action, "not_found")


@override_settings(CACHES=_CACHES)
class ContributeDoiEndpointTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user(username="c@example.com", email="c@example.com", password="pw12345!")
        for target in ("build_openalex_fields", "enrich_work_from_openaire", "fetch_copernicus_abstract"):
            default = ({}, {}) if target == "build_openalex_fields" else None
            p = patch(f"works.harvesting.crossref.{target}", return_value=default)
            p.start()
            self.addCleanup(p.stop)

    def test_requires_authentication(self):
        resp = self.client.post(CONTRIBUTE_URL, {"doi": "10.1/x"}, content_type="application/json")
        self.assertIn(resp.status_code, (401, 403))

    def test_invalid_doi_returns_400(self):
        self.client.login(username="c@example.com", password="pw12345!")
        resp = self.client.post(CONTRIBUTE_URL, {"doi": "not-a-doi"}, content_type="application/json")
        self.assertEqual(resp.status_code, 400)

    def test_existing_doi_returns_200_with_url(self):
        work = Work.objects.create(title="Existing", doi="10.1234/Exist", status="p")
        self.client.login(username="c@example.com", password="pw12345!")
        # case-insensitive match on the stored DOI
        resp = self.client.post(
            CONTRIBUTE_URL, {"doi": "https://doi.org/10.1234/exist"}, content_type="application/json"
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertTrue(body["exists"])
        self.assertEqual(body["work_id"], work.id)
        self.assertIn("work_url", body)

    @responses.activate
    def test_new_doi_creates_work_with_provenance_and_contribution(self):
        responses.add(
            responses.GET,
            "https://api.crossref.org/works/10.1234/new1",
            json=_crossref_single("10.1234/new1"),
            status=200,
        )
        self.client.login(username="c@example.com", password="pw12345!")
        resp = self.client.post(CONTRIBUTE_URL, {"doi": "10.1234/new1"}, content_type="application/json")
        self.assertEqual(resp.status_code, 201)
        body = resp.json()
        self.assertTrue(body["created"])
        work = Work.objects.get(id=body["work_id"])
        self.assertEqual(work.doi, "10.1234/new1")
        # provenance event recorded
        events = (work.provenance or {}).get("events", [])
        self.assertTrue(any(e.get("type") == "doi_contribution" for e in events))
        # recognition-board row recorded
        self.assertTrue(Contribution.objects.filter(user=self.user, work=work, kind=Contribution.DOI).exists())

    @responses.activate
    def test_unknown_doi_returns_404(self):
        responses.add(
            responses.GET,
            "https://api.crossref.org/works/10.1234/none",
            status=404,
        )
        self.client.login(username="c@example.com", password="pw12345!")
        resp = self.client.post(CONTRIBUTE_URL, {"doi": "10.1234/none"}, content_type="application/json")
        self.assertEqual(resp.status_code, 404)


class ContributedDoisStatisticTests(TestCase):
    def test_calculate_statistics_counts_doi_contributions(self):
        from works.utils.statistics import calculate_statistics

        work = Work.objects.create(title="W", doi="10.1234/stat", status="h")
        user = User.objects.create_user(username="s@example.com", email="s@example.com", password="pw")
        Contribution.objects.create(user=user, work=work, kind=Contribution.DOI)
        Contribution.objects.create(user=user, work=work, kind=Contribution.SPATIAL)

        stats = calculate_statistics()
        self.assertEqual(stats["contributed_dois"], 1)


@override_settings(CACHES=_CACHES)
class HarvestCrossrefDoiOnlineTests(TestCase):
    """Live end-to-end harvest of a single real DOI through Crossref."""

    @tag("online")
    def test_real_doi_creates_work(self):
        doi = "10.5194/gi-9-219-2020"
        try:
            work, action = harvest_crossref_doi(doi)
        except requests.RequestException as exc:
            self.skipTest(f"Crossref unreachable: {exc}")
        if action == "not_found":
            self.skipTest("Crossref returned no record (endpoint hiccup)")
        self.assertEqual(action, "created")
        self.assertEqual(work.doi, doi)
        self.assertEqual(work.status, "h")
        self.assertTrue(work.title)
