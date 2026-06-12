# SPDX-FileCopyrightText: 2026 OPTIMETA and KOMET projects <https://projects.tib.eu/komet>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests for the Mountain Wetlands Repository (MaRESS) harvester (issue #192).

The MaRESS API is mocked end-to-end — these tests are pure unit tests and do
not hit the live endpoint.
"""

import json
from datetime import date as _date
from pathlib import Path
from unittest.mock import MagicMock, patch

from django.test import TestCase

from works.models import Collection, HarvestingEvent, Source, Work

SAMPLE_JSON = Path(__file__).resolve().parent / "harvesting" / "mountain_wetlands" / "items_sample.json"


def _mock_response(payload):
    resp = MagicMock()
    resp.ok = True
    resp.status_code = 200
    resp.json.return_value = payload
    resp.headers = {"Content-Type": "application/json"}
    return resp


class MountainWetlandsHarvesterTests(TestCase):
    """Cover the parse + persist path with a recorded API response."""

    @classmethod
    def setUpTestData(cls):
        cls.payload = json.loads(SAMPLE_JSON.read_text())

    def setUp(self):
        self.collection = Collection.objects.create(
            identifier="mountain-wetlands",
            name="Mountain Wetlands",
            is_published=True,
        )
        self.source = Source.objects.create(
            name="MaRESS",
            url_field="https://andes.mountain-wetlands-repository.info/api/v1/items/",
            source_type="mountain-wetlands",
            collection=self.collection,
        )

    def _patched_session(self, payload):
        """Patch _mwr_session() so the harvester sees one page of the recorded payload."""
        session = MagicMock()
        session.get.return_value = _mock_response(payload)
        return patch("works.harvesting.mountain_wetlands._mwr_session", return_value=session)

    def _no_op_openalex(self):
        """Force build_openalex_fields() to return ``({}, {})`` — i.e. no match
        and no enrichment. Lets the harvester tests focus on the API-shape
        handling without exercising the live OpenAlex matcher."""
        return patch("works.harvesting.mountain_wetlands.build_openalex_fields", return_value=({}, {}))

    def test_creates_one_work_per_item(self):
        with self._patched_session(self.payload), self._no_op_openalex():
            from works.tasks import harvest_mountain_wetlands

            saved, processed = harvest_mountain_wetlands(self.source.id)

        self.assertEqual(processed, 3)
        self.assertEqual(saved, 3)
        self.assertEqual(Work.objects.count(), 3)

    def test_geometry_built_from_study_sites(self):
        with self._patched_session(self.payload), self._no_op_openalex():
            from works.tasks import harvest_mountain_wetlands

            harvest_mountain_wetlands(self.source.id)

        baied = Work.objects.get(title__startswith="Evolution of High Andean")
        self.assertIsNotNone(baied.geometry)
        self.assertFalse(baied.geometry.empty)
        self.assertEqual(baied.geometry.geom_type, "GeometryCollection")
        # One study site → one Point in the GeometryCollection
        self.assertEqual(baied.geometry.num_geom, 1)
        pt = baied.geometry[0]
        self.assertAlmostEqual(pt.x, -69.2239, places=3)
        self.assertAlmostEqual(pt.y, -18.1887, places=3)

    def test_record_without_study_sites_has_empty_geometry(self):
        with self._patched_session(self.payload), self._no_op_openalex():
            from works.tasks import harvest_mountain_wetlands

            harvest_mountain_wetlands(self.source.id)

        no_sites = Work.objects.get(title="Record Without Study Sites")
        self.assertTrue(no_sites.geometry is None or no_sites.geometry.empty)

    def test_year_only_date_parsed_to_jan_1(self):
        with self._patched_session(self.payload), self._no_op_openalex():
            from works.tasks import harvest_mountain_wetlands

            harvest_mountain_wetlands(self.source.id)

        baied = Work.objects.get(title__startswith="Evolution of High Andean")
        self.assertEqual(baied.publicationDate, _date(1993, 1, 1))
        # MaRESS carries no study time period, so the temporal extent stays
        # unset — the publication year is not a substitute for it.
        self.assertIsNone(baied.timeperiod_startdate)
        self.assertIsNone(baied.timeperiod_enddate)

    def test_provenance_records_original_record_and_match_status(self):
        with self._patched_session(self.payload), self._no_op_openalex():
            from works.tasks import harvest_mountain_wetlands

            harvest_mountain_wetlands(self.source.id)

        baied = Work.objects.get(title__startswith="Evolution of High Andean")
        prov = baied.provenance
        self.assertIsInstance(prov, dict)
        self.assertEqual(prov["harvest"]["harvester"], "harvest_mountain_wetlands")
        self.assertEqual(prov["harvest"]["external_id"], "a88d9783-0606-4bb9-a6ec-35610f9172e5")
        # Original API record stored verbatim so curators can re-run enrichment.
        self.assertEqual(prov["harvest"]["original_record"]["id"], "a88d9783-0606-4bb9-a6ec-35610f9172e5")
        # Baied has DOI + authors from the API — OpenAlex is skipped.
        self.assertEqual(prov["openalex_match"]["status"], "skipped")
        self.assertEqual(prov["openalex_match"]["first_author_surname_used"], "Baied")

    def test_first_author_surname_skips_et_al(self):
        with self._patched_session(self.payload), self._no_op_openalex():
            from works.tasks import harvest_mountain_wetlands

            harvest_mountain_wetlands(self.source.id)

        # Barros + et al. → 'Barros' should be the first-author signal, not 'et al.'.
        barros = Work.objects.get(title__startswith="Short-Term Effects")
        self.assertEqual(
            barros.provenance["openalex_match"]["first_author_surname_used"],
            "Barros",
        )

    def test_works_are_added_to_source_collection(self):
        with self._patched_session(self.payload), self._no_op_openalex():
            from works.tasks import harvest_mountain_wetlands

            harvest_mountain_wetlands(self.source.id)

        for w in Work.objects.all():
            self.assertIn(
                self.collection, list(w.collections.all()), f"work {w.pk} should be in mountain-wetlands collection"
            )

    def test_idempotent_re_run_does_not_duplicate(self):
        with self._patched_session(self.payload), self._no_op_openalex():
            from works.tasks import harvest_mountain_wetlands

            harvest_mountain_wetlands(self.source.id)
            self.assertEqual(Work.objects.count(), 3)

            # Second run: same payload, same items — should be a no-op.
            saved, processed = harvest_mountain_wetlands(self.source.id)
            self.assertEqual(saved, 0, "re-running on the same payload should not save new works")
            self.assertEqual(Work.objects.count(), 3)

    def test_max_records_caps_processing(self):
        with self._patched_session(self.payload), self._no_op_openalex():
            from works.tasks import harvest_mountain_wetlands

            saved, processed = harvest_mountain_wetlands(self.source.id, max_records=1)

        self.assertEqual(processed, 1)
        self.assertEqual(saved, 1)
        self.assertEqual(Work.objects.count(), 1)

    def test_harvesting_event_records_counts(self):
        with self._patched_session(self.payload), self._no_op_openalex():
            from works.tasks import harvest_mountain_wetlands

            harvest_mountain_wetlands(self.source.id)

        event = HarvestingEvent.objects.filter(source=self.source).latest("started_at")
        self.assertEqual(event.status, "completed")
        self.assertEqual(event.records_added, 3)
        # Two of three sample records have study_sites with valid coords.
        self.assertEqual(event.records_with_spatial, 2)


class MountainWetlandsOpenAlexMatchTests(TestCase):
    """Verify the harvester records OpenAlex match status correctly when the
    matcher returns a verified hit, a candidate hit, or nothing."""

    @classmethod
    def setUpTestData(cls):
        cls.payload = json.loads(SAMPLE_JSON.read_text())

    def setUp(self):
        self.source = Source.objects.create(
            name="MaRESS",
            url_field="https://andes.mountain-wetlands-repository.info/api/v1/items/",
            source_type="mountain-wetlands",
        )

    def _patched_session(self, payload):
        session = MagicMock()
        session.get.return_value = _mock_response(payload)
        return patch("works.harvesting.mountain_wetlands._mwr_session", return_value=session)

    def test_api_doi_persisted_on_work_and_openalex_skipped(self):
        """When the API carries both DOI and authors, the DOI is saved and
        OpenAlex is not called (rate-limit budget preserved)."""
        mock_build = MagicMock(return_value=({}, {}))

        with (
            self._patched_session(self.payload),
            patch("works.harvesting.mountain_wetlands.build_openalex_fields", mock_build),
        ):
            from works.tasks import harvest_mountain_wetlands

            harvest_mountain_wetlands(self.source.id)

        baied = Work.objects.get(title__startswith="Evolution of High Andean")
        self.assertEqual(baied.doi, "10.2307/3673632")
        self.assertEqual(baied.provenance["metadata_sources"].get("doi"), "original_source")
        self.assertEqual(baied.provenance["openalex_match"]["status"], "skipped")

        barros = Work.objects.get(title__startswith="Short-Term Effects")
        self.assertEqual(barros.provenance["openalex_match"]["status"], "skipped")

        # Only the no-DOI / no-author record triggers an OpenAlex call.
        self.assertEqual(mock_build.call_count, 1)

    def test_api_doi_normalised_from_https_form(self):
        with (
            self._patched_session(self.payload),
            patch("works.harvesting.mountain_wetlands.build_openalex_fields", return_value=({}, {})),
        ):
            from works.tasks import harvest_mountain_wetlands

            harvest_mountain_wetlands(self.source.id)

        barros = Work.objects.get(title__startswith="Short-Term Effects")
        self.assertEqual(barros.doi, "10.1657/1938-4246-46.2.333")

    def test_openalex_doi_used_when_api_doi_missing(self):
        verified_fields = {
            "openalex_id": "https://openalex.org/W123",
            "openalex_ids": {"doi": "https://doi.org/10.1234/test"},
            "openalex_is_retracted": False,
            "openalex_open_access_status": "gold",
            "authors": [],
            "topics": ["Andean Ecology"],
        }
        with (
            self._patched_session(self.payload),
            patch(
                "works.harvesting.mountain_wetlands.build_openalex_fields",
                side_effect=lambda title, doi, author, existing_metadata=None: (
                    (dict(verified_fields), {"topics": "openalex"})
                    if title.startswith("Record Without Study Sites")
                    else ({}, {})
                ),
            ),
        ):
            from works.tasks import harvest_mountain_wetlands

            harvest_mountain_wetlands(self.source.id)

        no_sites = Work.objects.get(title="Record Without Study Sites")
        self.assertEqual(no_sites.doi, "10.1234/test")
        self.assertEqual(no_sites.openalex_id, "https://openalex.org/W123")
        self.assertEqual(no_sites.provenance["openalex_match"]["status"], "verified")
        self.assertEqual(no_sites.provenance["metadata_sources"].get("doi"), "openalex")

    def test_candidate_match_on_no_doi_record_stores_info_but_no_doi(self):
        """A candidate OpenAlex match on a no-DOI record stores the candidate
        info for curators but does not write a DOI (only verified matches do)."""
        candidate_fields = {
            "openalex_id": None,
            "openalex_match_info": [
                {
                    "openalex_id": "https://openalex.org/W999",
                    "title": "Similar but not exact",
                    "match_type": "title+author",
                },
            ],
        }
        with (
            self._patched_session(self.payload),
            patch(
                "works.harvesting.mountain_wetlands.build_openalex_fields",
                side_effect=lambda title, doi, author, existing_metadata=None: (
                    (dict(candidate_fields), {}) if title == "Record Without Study Sites" else ({}, {})
                ),
            ),
        ):
            from works.tasks import harvest_mountain_wetlands

            harvest_mountain_wetlands(self.source.id)

        no_sites = Work.objects.get(title="Record Without Study Sites")
        self.assertIsNone(no_sites.doi)
        self.assertEqual(no_sites.provenance["openalex_match"]["status"], "candidate")
        self.assertTrue(no_sites.openalex_match_info)
