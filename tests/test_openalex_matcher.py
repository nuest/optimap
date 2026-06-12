# SPDX-FileCopyrightText: 2026 OPTIMETA and KOMET projects <https://projects.tib.eu/komet>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Unit tests for ``works.openalex_matcher.OpenAlexMatcher``.

The matcher is the shared OpenAlex enrichment service used by the OAI-PMH /
RSS / Crossref / MWR harvesters and by the ``backfill_openalex`` management
command. ``extract_openalex_fields`` is the field-mapping step that decides
what gets ``setattr``-ed onto an existing ``Work`` record.
"""

from django.test import TestCase

from works.openalex_matcher import OpenAlexMatcher


class ExtractOpenAlexFieldsTests(TestCase):
    """Mapping from a raw OpenAlex ``works`` payload to ``Work``-model fields."""

    def setUp(self):
        self.matcher = OpenAlexMatcher()

    def _payload(self, **overrides):
        payload = {
            "id": "https://openalex.org/W123",
            "doi": "https://doi.org/10.5194/agile-giss-1-1-2020",
            "is_retracted": False,
            "ids": {"doi": "https://doi.org/10.5194/agile-giss-1-1-2020"},
            "type": "proceedings-article",
            "biblio": {"volume": "1", "issue": "1", "first_page": "1", "last_page": "9"},
            "authorships": [{"author": {"display_name": "Jane Doe"}}],
            "keywords": [{"display_name": "GIS"}],
            "topics": [{"display_name": "Cartography"}],
            "open_access": {"is_oa": True, "oa_status": "gold"},
            "primary_location": {"source": {"type": "journal"}},
        }
        payload.update(overrides)
        return payload

    def test_returns_bare_doi_when_openalex_has_one(self):
        # Regression for the AGILE-GISS DOI gap: ``backfill_openalex`` writes
        # every key in this dict via ``setattr``, so emitting ``doi`` here is
        # what lets the backfill recover an empty ``Work.doi`` from a
        # successful OpenAlex match.
        out = self.matcher.extract_openalex_fields(self._payload())
        self.assertEqual(out["doi"], "10.5194/agile-giss-1-1-2020")

    def test_strips_http_and_bare_doi_org_prefixes(self):
        for raw in (
            "http://doi.org/10.5194/x",
            "doi.org/10.5194/x",
            "10.5194/x",
        ):
            with self.subTest(raw=raw):
                out = self.matcher.extract_openalex_fields(self._payload(doi=raw))
                self.assertEqual(out["doi"], "10.5194/x")

    def test_omits_doi_key_when_openalex_has_none(self):
        # Important: the backfill loop is a blind ``setattr`` over the dict
        # keys. Emitting ``'doi': None`` would blank a populated DOI on the
        # work record, so we must omit the key entirely instead.
        out = self.matcher.extract_openalex_fields(self._payload(doi=None))
        self.assertNotIn("doi", out)

    def test_other_fields_remain_unchanged(self):
        # Sanity check: the new ``doi`` key doesn't disturb the existing
        # field set the backfill command depends on.
        out = self.matcher.extract_openalex_fields(self._payload())
        self.assertEqual(out["openalex_id"], "https://openalex.org/W123")
        self.assertEqual(out["type"], "proceedings-article")
        self.assertEqual(out["volume"], "1")
        self.assertEqual(out["authors"], ["Jane Doe"])
        self.assertEqual(out["keywords"], ["GIS"])
        self.assertEqual(out["topics"], ["Cartography"])
        self.assertEqual(out["openalex_open_access_status"], "gold")
        self.assertEqual(out["openalex_fulltext_origin"], "journal")
