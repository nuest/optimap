# SPDX-FileCopyrightText: 2026 OPTIMETA and KOMET projects <https://projects.tib.eu/komet>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests for OpenAIRE enrichment (a second enrichment source besides OpenAlex)."""

import os
from io import StringIO
from unittest.mock import patch

import django
from django.test import TestCase, override_settings, tag

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "optimap.settings")
django.setup()

from django.core.management import call_command

from works.harvesting.common import (
    HarvestStats,
    HarvestWarningCollector,
    _carefully_update_work,
    complete_harvest,
)
from works.harvesting.enrichment import apply_enrichment
from works.harvesting.openaire import (
    build_openaire_fields,
    enrich_event_from_openaire,
    enrich_work_from_openaire,
    fetch_openaire_record,
)
from works.models import HarvestingEvent, Source, Work

# A representative OpenAIRE Graph API record (shape verified live for
# 10.1007/978-3-540-78946-8_4). Two descriptions so the "longest wins" rule is
# exercised; subjects mix free-text keywords with automated SDG/FOS schemes.
FAKE_RECORD = {
    "id": "doi_dedup___::abc123",
    "mainTitle": "Evaluation of the Geometric Accuracy of 3D City Models",
    "descriptions": [
        "Short note.",
        "A considerably longer abstract that describes the methods and results in full and should be the one selected.",
    ],
    "authors": [
        {"fullName": "Gerald Gruber", "rank": 1},
        {"fullName": "Christian Menard", "rank": 2},
        {"fullName": "", "rank": 3},
    ],
    "subjects": [
        {"subject": {"scheme": "SDG", "value": "11. Sustainability"}},
        {"subject": {"scheme": "keyword", "value": "city models"}},
        {"subject": {"scheme": "", "value": "accuracy"}},
        {"subject": {"scheme": "FOS", "value": "Engineering"}},
    ],
}


class BuildOpenaireFieldsTest(TestCase):
    """Pure extraction from an OpenAIRE record (no DB / network)."""

    def test_extracts_longest_abstract(self):
        fields = build_openaire_fields(FAKE_RECORD)
        self.assertIn("abstract", fields)
        self.assertTrue(fields["abstract"].startswith("A considerably longer"))

    def test_keywords_drop_automated_schemes(self):
        fields = build_openaire_fields(FAKE_RECORD)
        # SDG and FOS classifications are dropped; free-text keywords kept.
        self.assertEqual(fields["keywords"], ["city models", "accuracy"])

    def test_authors_from_fullname_skip_blanks(self):
        fields = build_openaire_fields(FAKE_RECORD)
        self.assertEqual(fields["authors"], ["Gerald Gruber", "Christian Menard"])

    def test_empty_record_yields_no_candidates(self):
        self.assertEqual(build_openaire_fields(None), {})
        self.assertEqual(build_openaire_fields({"descriptions": [], "subjects": [], "authors": []}), {})


class ApplyEnrichmentTest(TestCase):
    """The fill-if-empty conflict policy + provenance recording."""

    def test_fills_empty_field_and_records_source(self):
        work = Work(title="t", abstract="")
        filled, offered = apply_enrichment(work, {"abstract": "From OpenAIRE"}, "openaire")
        self.assertEqual(work.abstract, "From OpenAIRE")
        self.assertEqual(filled, ["abstract"])
        self.assertEqual(offered, [])
        self.assertEqual(work.provenance["metadata_sources"]["abstract"], "openaire")

    def test_does_not_overwrite_existing_value(self):
        work = Work(title="t", abstract="Existing abstract")
        filled, offered = apply_enrichment(work, {"abstract": "From OpenAIRE"}, "openaire")
        self.assertEqual(work.abstract, "Existing abstract")
        self.assertEqual(filled, [])
        self.assertEqual(offered, ["abstract"])
        self.assertNotIn("abstract", work.provenance.get("metadata_sources", {}))

    def test_blank_candidate_is_skipped(self):
        work = Work(title="t", abstract="")
        filled, offered = apply_enrichment(work, {"abstract": "   "}, "openaire")
        self.assertEqual(filled, [])
        self.assertEqual(offered, [])
        self.assertEqual(work.abstract, "")


class EnrichWorkFromOpenaireTest(TestCase):
    def setUp(self):
        self.work = Work.objects.create(title="t", doi="10.1007/978-x", abstract="", status="h")

    @patch("works.harvesting.openaire.fetch_openaire_record", return_value=FAKE_RECORD)
    def test_match_fills_and_records_provenance(self, _mock):
        changed = enrich_work_from_openaire(self.work)
        self.work.refresh_from_db()
        self.assertTrue(changed)
        self.assertTrue(self.work.abstract.startswith("A considerably longer"))
        self.assertEqual(self.work.provenance["metadata_sources"]["abstract"], "openaire")
        self.assertEqual(self.work.provenance["openaire_match"]["status"], "matched")
        self.assertEqual(self.work.provenance["openaire_match"]["openaire_id"], "doi_dedup___::abc123")
        events = self.work.provenance["events"]
        self.assertEqual(events[-1]["type"], "openaire_enrich")
        self.assertIn("abstract", events[-1]["fields_filled"])

    @patch("works.harvesting.openaire.fetch_openaire_record", return_value=FAKE_RECORD)
    def test_offered_not_applied_logged(self, _mock):
        self.work.abstract = "Curator-supplied abstract"
        self.work.save(update_fields=["abstract"])
        enrich_work_from_openaire(self.work)
        self.work.refresh_from_db()
        self.assertEqual(self.work.abstract, "Curator-supplied abstract")
        event = self.work.provenance["events"][-1]
        self.assertIn("abstract", event["fields_offered_not_applied"])
        self.assertNotIn("abstract", event.get("fields_filled") or [])

    @patch("works.harvesting.openaire.fetch_openaire_record", return_value=None)
    def test_no_match_records_status_none(self, _mock):
        changed = enrich_work_from_openaire(self.work)
        self.work.refresh_from_db()
        self.assertFalse(changed)
        self.assertEqual(self.work.provenance["openaire_match"]["status"], "none")


class CarefulUpdatePreservesEnrichedFieldsTest(TestCase):
    """A re-harvest that brings nothing must not wipe an enriched abstract."""

    def setUp(self):
        self.source = Source.objects.create(name="S", url_field="https://e.x/oai")
        self.event = HarvestingEvent.objects.create(source=self.source, status="in_progress")

    def test_reharvest_keeps_nonempty_abstract(self):
        work = Work.objects.create(
            title="old", doi="10.1/keep", abstract="Enriched abstract", source=self.source, status="h"
        )
        new_fields = {"title": "new title", "abstract": None, "provenance": {"harvest": {}}}
        _carefully_update_work(work, new_fields, self.event)
        work.refresh_from_db()
        self.assertEqual(work.abstract, "Enriched abstract")
        self.assertEqual(work.title, "new title")


class EnrichEventSweepTest(TestCase):
    def setUp(self):
        self.source = Source.objects.create(name="S", url_field="https://e.x/oai")
        self.event = HarvestingEvent.objects.create(source=self.source, status="in_progress")

    @patch("works.harvesting.openaire.fetch_openaire_record", return_value=FAKE_RECORD)
    def test_sweep_only_touches_missing_field_works(self, mock_fetch):
        missing = Work.objects.create(title="m", doi="10.1/m", abstract="", status="h", job=self.event)
        complete = Work.objects.create(
            title="c", doi="10.1/c", abstract="has one", authors=["A"], keywords=["k"], status="h", job=self.event
        )
        no_doi = Work.objects.create(title="n", abstract="", status="h", job=self.event)

        updated = enrich_event_from_openaire(self.event.id, throttle=0)

        missing.refresh_from_db()
        complete.refresh_from_db()
        self.assertTrue(missing.abstract.startswith("A considerably longer"))
        self.assertEqual(complete.abstract, "has one")
        self.assertEqual(updated, 1)
        # only the missing-field, DOI-bearing work was looked up
        looked_up = {c.args[0] for c in mock_fetch.call_args_list}
        self.assertEqual(looked_up, {"10.1/m"})
        self.assertNotIn(no_doi.doi, looked_up)


class CompleteHarvestEnqueueTest(TestCase):
    def setUp(self):
        self.source = Source.objects.create(name="S", url_field="https://e.x/oai")
        self.event = HarvestingEvent.objects.create(source=self.source, status="in_progress")

    @override_settings(OPTIMAP_OPENAIRE_ENRICH_ON_HARVEST=True)
    @patch("works.harvesting.common.fetch_and_store_crossref_works_count", return_value=None)
    @patch("works.harvesting.common.fetch_and_store_oai_works_count", return_value=None)
    @patch("works.harvesting.common.fetch_and_store_openalex_source_stats", return_value=None)
    @patch("works.harvesting.common.async_task")
    def test_enqueues_sweep_when_enabled(self, mock_async, *_stats):
        complete_harvest(self.event, HarvestStats(), HarvestWarningCollector())
        mock_async.assert_called_once()
        self.assertEqual(mock_async.call_args[0][0], "works.harvesting.openaire.enrich_event_from_openaire")
        self.assertEqual(mock_async.call_args[0][1], self.event.id)

    @override_settings(OPTIMAP_OPENAIRE_ENRICH_ON_HARVEST=False)
    @patch("works.harvesting.common.fetch_and_store_crossref_works_count", return_value=None)
    @patch("works.harvesting.common.fetch_and_store_oai_works_count", return_value=None)
    @patch("works.harvesting.common.fetch_and_store_openalex_source_stats", return_value=None)
    @patch("works.harvesting.common.async_task")
    def test_skips_sweep_when_disabled(self, mock_async, *_stats):
        complete_harvest(self.event, HarvestStats(), HarvestWarningCollector())
        mock_async.assert_not_called()


class EnrichOpenaireCommandTest(TestCase):
    def setUp(self):
        self.work = Work.objects.create(title="t", doi="10.1007/978-c", abstract="", status="h")

    @patch("works.harvesting.openaire.fetch_openaire_record", return_value=FAKE_RECORD)
    def test_command_fills_abstract(self, _mock):
        out = StringIO()
        call_command("enrich_openaire", "--throttle", "0", stdout=out)
        self.work.refresh_from_db()
        self.assertTrue(self.work.abstract.startswith("A considerably longer"))
        self.assertIn("Updated", out.getvalue())

    @patch("works.harvesting.openaire.fetch_openaire_record", return_value=FAKE_RECORD)
    def test_command_dry_run_writes_nothing(self, _mock):
        call_command("enrich_openaire", "--throttle", "0", "--dry-run", stdout=StringIO())
        self.work.refresh_from_db()
        self.assertEqual(self.work.abstract, "")


@tag("online")
class OpenaireOnlineTest(TestCase):
    """Hits the real OpenAIRE Graph API; self-skips when unreachable."""

    def test_real_lookup_returns_abstract(self):
        record = fetch_openaire_record("10.1007/978-3-540-78946-8_4")
        if record is None:
            self.skipTest("OpenAIRE endpoint unreachable")
        fields = build_openaire_fields(record)
        self.assertTrue(fields.get("abstract"))
