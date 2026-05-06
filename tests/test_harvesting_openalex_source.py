# SPDX-FileCopyrightText: 2026 OPTIMETA and KOMET projects <https://projects.tib.eu/komet>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests for the OpenAlex-as-source harvester.

Covers:
- pure helpers (`_strip_doi_prefix`, `_reconstruct_abstract`,
  `_resolve_openalex_source_id`, `_authors_from_authorships`,
  `_keywords_from_payload`, `_topics_from_payload`, `_landing_page_for`),
- the item-to-kwargs mapping (`_openalex_item_to_work_kwargs`),
- end-to-end `harvest_openalex_source` with `responses` mocking the
  OpenAlex API (single page, multi-page cursor pagination, and the
  same-source-dedup skip path),
- one `@tag('online')` smoke test that hits api.openalex.org with
  `max_records=2`.
"""

import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "optimap.settings")
django.setup()

import responses
from datetime import date
from django.test import TestCase, tag

from works.models import HarvestingEvent, Source, Work
from works.harvesting.openalex_source import (
    _authors_from_authorships,
    _keywords_from_payload,
    _landing_page_for,
    _openalex_item_to_work_kwargs,
    _reconstruct_abstract,
    _resolve_openalex_source_id,
    _strip_doi_prefix,
    _topics_from_payload,
)
from works.tasks import harvest_openalex_source


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------

class StripDoiPrefixTests(TestCase):

    def test_returns_none_for_falsy(self):
        self.assertIsNone(_strip_doi_prefix(None))
        self.assertIsNone(_strip_doi_prefix(""))

    def test_strips_https_doi_org(self):
        out = _strip_doi_prefix("https://doi.org/10.5194/agile-giss-1-1-2020")
        self.assertEqual(out, "10.5194/agile-giss-1-1-2020")

    def test_strips_http_doi_org(self):
        out = _strip_doi_prefix("http://doi.org/10.5194/x")
        self.assertEqual(out, "10.5194/x")

    def test_strips_bare_doi_org_prefix(self):
        out = _strip_doi_prefix("doi.org/10.5194/x")
        self.assertEqual(out, "10.5194/x")

    def test_passes_through_bare_doi(self):
        self.assertEqual(_strip_doi_prefix("10.5194/x"), "10.5194/x")


class ReconstructAbstractTests(TestCase):

    def test_returns_none_for_empty(self):
        self.assertIsNone(_reconstruct_abstract(None))
        self.assertIsNone(_reconstruct_abstract({}))

    def test_reconstructs_in_position_order(self):
        # "the quick brown fox" — words at positions 0..3
        idx = {"quick": [1], "the": [0], "fox": [3], "brown": [2]}
        self.assertEqual(_reconstruct_abstract(idx), "the quick brown fox")

    def test_handles_repeated_words(self):
        # "we test we win" — "we" appears at 0 and 2
        idx = {"we": [0, 2], "test": [1], "win": [3]}
        self.assertEqual(_reconstruct_abstract(idx), "we test we win")

    def test_word_with_empty_position_list_is_dropped(self):
        idx = {"hello": [0], "ghost": []}
        self.assertEqual(_reconstruct_abstract(idx), "hello")


class ResolveOpenAlexSourceIdTests(TestCase):

    def _src(self, **fields):
        return Source.objects.create(
            name=fields.pop("name", "x"),
            url_field=fields.pop("url_field", "https://example.test"),
            **fields,
        )

    def test_prefers_openalex_id_field(self):
        s = self._src(openalex_id="S4210203054",
                      openalex_url="https://openalex.org/sources/S9999",
                      url_field="https://example.test/no-s-here")
        self.assertEqual(_resolve_openalex_source_id(s), "S4210203054")

    def test_falls_back_to_openalex_url(self):
        s = self._src(openalex_url="https://openalex.org/sources/S4210203054",
                      url_field="https://example.test/no-s-here")
        self.assertEqual(_resolve_openalex_source_id(s), "S4210203054")

    def test_falls_back_to_url_field(self):
        s = self._src(url_field="https://api.openalex.org/sources/S4210203054")
        self.assertEqual(_resolve_openalex_source_id(s), "S4210203054")

    def test_returns_none_when_no_token_anywhere(self):
        s = self._src(url_field="https://example.test/no-token")
        self.assertIsNone(_resolve_openalex_source_id(s))


class AuthorsFromAuthorshipsTests(TestCase):

    def test_empty_or_none_returns_empty_list(self):
        self.assertEqual(_authors_from_authorships(None), [])
        self.assertEqual(_authors_from_authorships([]), [])

    def test_extracts_display_name(self):
        out = _authors_from_authorships([
            {"author": {"display_name": "Jane Doe"}},
            {"author": {"display_name": "John Smith"}},
        ])
        self.assertEqual(out, ["Jane Doe", "John Smith"])

    def test_falls_back_to_raw_author_name(self):
        out = _authors_from_authorships([
            {"author": {}, "raw_author_name": "Anon Y. Mous"},
        ])
        self.assertEqual(out, ["Anon Y. Mous"])

    def test_drops_entries_with_no_name(self):
        out = _authors_from_authorships([
            {"author": {"display_name": "Real Person"}},
            {"author": {}},  # no name anywhere — dropped
        ])
        self.assertEqual(out, ["Real Person"])


class KeywordsAndTopicsTests(TestCase):

    def test_keywords_dict_shape(self):
        out = _keywords_from_payload({
            "keywords": [
                {"display_name": "geospatial"},
                {"keyword": "remote sensing"},
            ],
        })
        self.assertEqual(out, ["geospatial", "remote sensing"])

    def test_keywords_string_shape(self):
        out = _keywords_from_payload({"keywords": ["a", "b"]})
        self.assertEqual(out, ["a", "b"])

    def test_keywords_missing_returns_empty(self):
        self.assertEqual(_keywords_from_payload({}), [])

    def test_topics_extracts_display_name_only(self):
        out = _topics_from_payload({
            "topics": [
                {"display_name": "GIS"},
                {"display_name": "Cartography"},
                {"id": "T1", "score": 0.9},  # no display_name — dropped
            ],
        })
        self.assertEqual(out, ["GIS", "Cartography"])


class LandingPageForTests(TestCase):

    def test_prefers_primary_location_landing_page(self):
        out = _landing_page_for({
            "primary_location": {"landing_page_url": "https://primary.test/"},
            "doi": "https://doi.org/10.x/y",
        })
        self.assertEqual(out, "https://primary.test/")

    def test_falls_back_to_doi(self):
        out = _landing_page_for({
            "primary_location": {},
            "doi": "https://doi.org/10.x/y",
        })
        self.assertEqual(out, "https://doi.org/10.x/y")

    def test_falls_back_to_locations(self):
        out = _landing_page_for({
            "primary_location": {},
            "locations": [{"landing_page_url": "https://alt.test/"}],
        })
        self.assertEqual(out, "https://alt.test/")

    def test_returns_none_when_nothing_known(self):
        self.assertIsNone(_landing_page_for({}))


# ---------------------------------------------------------------------------
# Item → Work kwargs
# ---------------------------------------------------------------------------

class OpenAlexItemToKwargsTests(TestCase):

    def setUp(self):
        self.source = Source.objects.create(
            name="OpenAlex Test",
            url_field="https://api.openalex.org/sources/S4210203054",
            source_type="openalex",
            openalex_id="S4210203054",
            default_work_type="proceedings-article",
        )
        self.event = HarvestingEvent.objects.create(
            source=self.source, status="in_progress",
        )

    def _item(self, **overrides):
        item = {
            "id": "https://openalex.org/W123",
            "doi": "https://doi.org/10.5194/agile-giss-6-2-2025",
            "title": "Sample paper",
            "display_name": "Sample paper",
            "publication_date": "2025-06-09",
            "type": "proceedings-article",
            "abstract_inverted_index": {"hello": [0], "world": [1]},
            "authorships": [
                {"author": {"display_name": "Jane Doe"}},
                {"author": {"display_name": "John Smith"}},
            ],
            "keywords": [{"display_name": "GIS"}],
            "topics": [{"display_name": "Cartography"}],
            "biblio": {
                "volume": "6",
                "issue": None,
                "first_page": "1",
                "last_page": "9",
            },
            "primary_location": {
                "landing_page_url": "https://agile-giss.copernicus.org/articles/6/2/2025/",
            },
            "ids": {"doi": "https://doi.org/10.5194/agile-giss-6-2-2025"},
            "open_access": {"oa_status": "gold"},
            "fulltext_origin": "publisher",
            "is_retracted": False,
        }
        item.update(overrides)
        return item

    def test_returns_none_when_no_doi_or_landing_page(self):
        item = {"title": "no identifier"}  # no doi, no primary_location, no locations
        out = _openalex_item_to_work_kwargs(item, self.source, self.event)
        self.assertIsNone(out)

    def test_maps_full_payload(self):
        out = _openalex_item_to_work_kwargs(self._item(), self.source, self.event)
        self.assertEqual(out["doi"], "10.5194/agile-giss-6-2-2025")
        self.assertEqual(out["title"], "Sample paper")
        self.assertEqual(out["abstract"], "hello world")
        self.assertEqual(out["publicationDate"], date(2025, 6, 9))
        self.assertEqual(out["authors"], ["Jane Doe", "John Smith"])
        self.assertEqual(out["keywords"], ["GIS"])
        self.assertEqual(out["topics"], ["Cartography"])
        self.assertEqual(out["volume"], "6")
        self.assertIsNone(out["issue"])
        self.assertEqual(out["first_page"], "1")
        self.assertEqual(out["last_page"], "9")
        self.assertEqual(out["openalex_id"], "https://openalex.org/W123")
        self.assertEqual(out["openalex_open_access_status"], "gold")
        self.assertEqual(out["status"], "h")
        self.assertEqual(out["type"], "proceedings-article")
        # No landing-page fetch happens — geometry is empty by design.
        self.assertTrue(out["geometry"].empty)
        self.assertEqual(out["timeperiod_startdate"], [])
        self.assertEqual(out["timeperiod_enddate"], [])

    def test_provenance_records_harvester_and_openalex_source(self):
        out = _openalex_item_to_work_kwargs(self._item(), self.source, self.event)
        prov = out["provenance"]
        self.assertEqual(prov["harvest"]["harvester"], "harvest_openalex_source")
        self.assertEqual(prov["harvest"]["openalex_source_id"], "S4210203054")
        self.assertEqual(prov["metadata_sources"]["openalex"], "primary")

    def test_url_falls_back_to_doi_url_when_no_landing_page(self):
        item = self._item(primary_location={}, locations=[])
        out = _openalex_item_to_work_kwargs(item, self.source, self.event)
        self.assertEqual(out["url"], "https://doi.org/10.5194/agile-giss-6-2-2025")

    def test_invalid_publication_date_becomes_none(self):
        out = _openalex_item_to_work_kwargs(
            self._item(publication_date="not-a-date"), self.source, self.event,
        )
        self.assertIsNone(out["publicationDate"])


# ---------------------------------------------------------------------------
# End-to-end with mocked OpenAlex API
# ---------------------------------------------------------------------------

OPENALEX_WORKS_URL = "https://api.openalex.org/works"


class HarvestOpenAlexSourceEndToEndTests(TestCase):

    def setUp(self):
        self.source = Source.objects.create(
            name="OpenAlex AGILE-GISS (test)",
            url_field="https://api.openalex.org/sources/S4210203054",
            source_type="openalex",
            openalex_id="S4210203054",
            harvest_interval_minutes=0,
            publisher_name="Copernicus Publications",
            is_oa=True,
            default_work_type="proceedings-article",
        )

    def _make_item(self, doi_suffix, title="A paper"):
        return {
            "id": f"https://openalex.org/W{doi_suffix.replace('-', '').replace('.', '')}",
            "doi": f"https://doi.org/10.5194/agile-giss-{doi_suffix}",
            "title": title,
            "display_name": title,
            "publication_date": "2025-06-09",
            "type": "proceedings-article",
            "abstract_inverted_index": {"abstract": [0], "text": [1]},
            "authorships": [{"author": {"display_name": "Anne Author"}}],
            "keywords": [{"display_name": "k1"}],
            "topics": [{"display_name": "t1"}],
            "biblio": {"volume": "6", "issue": None, "first_page": "1", "last_page": "9"},
            "primary_location": {
                "landing_page_url": f"https://agile-giss.copernicus.org/articles/6/{doi_suffix}/",
            },
            "ids": {},
            "open_access": {"oa_status": "gold"},
            "fulltext_origin": "publisher",
            "is_retracted": False,
        }

    def _response(self, items, next_cursor=None):
        return {
            "meta": {
                "count": len(items),
                "next_cursor": next_cursor or "",
                "per_page": 200,
            },
            "results": items,
        }

    @responses.activate
    def test_end_to_end_single_page(self):
        items = [self._make_item("6-2-2025"), self._make_item("6-3-2025")]
        responses.add(
            responses.GET, OPENALEX_WORKS_URL,
            json=self._response(items), status=200,
        )

        harvest_openalex_source(self.source.id)

        works = Work.objects.filter(source=self.source).order_by("doi")
        self.assertEqual(works.count(), 2)
        self.assertEqual(
            list(works.values_list("doi", flat=True)),
            ["10.5194/agile-giss-6-2-2025", "10.5194/agile-giss-6-3-2025"],
        )
        for w in works:
            self.assertEqual(w.status, "h")
            self.assertEqual(w.authors, ["Anne Author"])
            self.assertEqual(w.openalex_open_access_status, "gold")

        event = HarvestingEvent.objects.filter(source=self.source).latest("started_at")
        self.assertEqual(event.status, "completed")
        self.assertEqual(event.records_added, 2)

    @responses.activate
    def test_cursor_pagination_walks_multiple_pages(self):
        page1 = self._response(
            [self._make_item("6-1-2025"), self._make_item("6-2-2025")],
            next_cursor="abc",
        )
        page2 = self._response(
            [self._make_item("6-3-2025")],
            next_cursor="",  # end of stream
        )
        # `responses` returns each registered response in order on repeated GETs.
        responses.add(responses.GET, OPENALEX_WORKS_URL, json=page1, status=200)
        responses.add(responses.GET, OPENALEX_WORKS_URL, json=page2, status=200)

        harvest_openalex_source(self.source.id)

        works = Work.objects.filter(source=self.source)
        self.assertEqual(works.count(), 3)
        # Two GETs to the works endpoint, no more — the empty next_cursor
        # ends the loop.
        works_calls = [c for c in responses.calls if "/works" in c.request.url]
        self.assertEqual(len(works_calls), 2)

    @responses.activate
    def test_max_records_caps_persistence(self):
        items = [self._make_item(f"6-{i}-2025") for i in range(1, 6)]
        responses.add(
            responses.GET, OPENALEX_WORKS_URL,
            json=self._response(items), status=200,
        )

        harvest_openalex_source(self.source.id, max_records=2)

        self.assertEqual(Work.objects.filter(source=self.source).count(), 2)

    @responses.activate
    def test_same_source_duplicates_are_skipped(self):
        # Pre-create a Work under this Source — re-harvesting must not double it.
        Work.objects.create(
            title="Pre-existing", doi="10.5194/agile-giss-6-2-2025",
            source=self.source, status="p",
        )
        items = [self._make_item("6-2-2025"), self._make_item("6-3-2025")]
        responses.add(
            responses.GET, OPENALEX_WORKS_URL,
            json=self._response(items), status=200,
        )

        harvest_openalex_source(self.source.id)

        # Two works total: the pre-existing + the new 6-3 (the 6-2 dup was skipped).
        self.assertEqual(Work.objects.filter(source=self.source).count(), 2)
        # Pre-existing work's status is preserved (never overwritten on skip).
        pre = Work.objects.get(doi="10.5194/agile-giss-6-2-2025")
        self.assertEqual(pre.status, "p")

    def test_raises_when_source_lacks_openalex_id(self):
        bad = Source.objects.create(
            name="No-OA-id source",
            url_field="https://example.test/no-token-here",
            source_type="openalex",
        )
        with self.assertRaises(RuntimeError):
            harvest_openalex_source(bad.id)
        # The HarvestingEvent should be marked failed.
        event = HarvestingEvent.objects.filter(source=bad).latest("started_at")
        self.assertEqual(event.status, "failed")


# ---------------------------------------------------------------------------
# Online smoke test — hits the real OpenAlex API
# ---------------------------------------------------------------------------

class HarvestOpenAlexSourceOnlineTests(TestCase):

    @tag("online")
    def test_real_openalex_harvest_agile_giss(self):
        """Smoke test: pull a couple of records from OpenAlex's AGILE-GISS source.

        Skips if the API is unreachable or returns no items (so the test is
        robust to transient OpenAlex outages).
        """
        import requests
        try:
            probe = requests.get(
                "https://api.openalex.org/works",
                params={
                    "filter": "primary_location.source.id:S4210203054",
                    "per-page": "1",
                },
                timeout=10,
            )
        except requests.RequestException as e:
            self.skipTest(f"OpenAlex unreachable: {e}")
        if not probe.ok:
            self.skipTest(f"OpenAlex returned HTTP {probe.status_code}")

        source = Source.objects.create(
            name="[online-test] AGILE-GISS",
            url_field="https://api.openalex.org/sources/S4210203054",
            source_type="openalex",
            openalex_id="S4210203054",
            default_work_type="proceedings-article",
            harvest_interval_minutes=0,
        )
        harvest_openalex_source(source.id, max_records=2)

        works = Work.objects.filter(source=source)
        self.assertGreater(works.count(), 0, "expected at least one work harvested")
        self.assertLessEqual(works.count(), 2, "max_records=2 should cap inserts")
        for w in works:
            self.assertTrue(w.title)
            self.assertTrue(w.openalex_id and w.openalex_id.startswith("https://openalex.org/W"))
            if w.doi:
                self.assertTrue(w.doi.startswith("10.5194/agile-giss-"))
