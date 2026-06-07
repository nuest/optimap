# SPDX-FileCopyrightText: 2026 OPTIMETA and KOMET projects <https://projects.tib.eu/komet>
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Tests for the Crossref-prefix harvester (Copernicus fallback).

Covers:
- the pure helpers (`_strip_jats`, `_build_crossref_filter`,
  `_crossref_item_to_work_kwargs`),
- the publisher-side abstract fetch (`fetch_copernicus_abstract`),
- end-to-end harvest_crossref_prefix with `responses` mocking the Crossref
  API and the publisher landing pages.
"""

import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "optimap.settings")
django.setup()

import responses
from datetime import date
from django.test import TestCase

from works.models import Source, HarvestingEvent, Work
from works.tasks import (
    _build_crossref_filter,
    _crossref_item_to_work_kwargs,
    _strip_jats,
    fetch_copernicus_abstract,
    harvest_crossref_prefix,
    parse_crossref_response_and_save_works,
)


SAMPLE_LANDING_HTML = """
<html><head>
  <meta name="citation_abstract" content="<p>Abstract. From the meta tag.</p>" />
</head><body>
  <div class="abstract">
    <strong>Abstract.</strong>
    The growing trend toward urbanisation and the increasingly frequent
    occurrence of extreme weather events emphasise the need for further
    monitoring. <em>Highlighted</em> follow-up sentence.
  </div>
</body></html>
"""

SAMPLE_LANDING_NO_ABSTRACT_DIV = """
<html><head>
  <meta name="citation_abstract" content="From the meta tag, fallback only." />
</head><body><p>No abstract div here.</p></body></html>
"""


class StripJatsTests(TestCase):

    def test_returns_none_for_falsy(self):
        self.assertIsNone(_strip_jats(""))
        self.assertIsNone(_strip_jats(None))

    def test_strips_jats_paragraph_wrapper(self):
        out = _strip_jats("<jats:p>Hello world.</jats:p>")
        self.assertEqual(out, "Hello world.")

    def test_strips_inline_markup(self):
        out = _strip_jats(
            "<jats:p>Hello <jats:italic>world</jats:italic> "
            "with <jats:sub>2</jats:sub> subscripts.</jats:p>"
        )
        self.assertEqual(out, "Hello world with 2 subscripts.")


class BuildCrossrefFilterTests(TestCase):

    def test_only_prefix(self):
        self.assertEqual(_build_crossref_filter("10.5194"), "prefix:10.5194")

    def test_with_source_titles(self):
        out = _build_crossref_filter(
            "10.5194",
            source_titles=["Earth System Science Data", "AGILE GIScience Series"],
        )
        self.assertIn("prefix:10.5194", out)
        self.assertIn("container-title:Earth System Science Data", out)
        self.assertIn("container-title:AGILE GIScience Series", out)

    def test_with_since(self):
        out = _build_crossref_filter("10.5194", since="2026-01-01")
        self.assertIn("from-update-date:2026-01-01", out)


class CrossrefItemConversionTests(TestCase):

    def setUp(self):
        self.source = Source.objects.create(
            name="Crossref Test", url_field="https://api.crossref.org/works",
            harvest_interval_minutes=60,
        )
        self.event = HarvestingEvent.objects.create(
            source=self.source, status="in_progress"
        )

    def _item(self, **overrides):
        item = {
            "DOI": "10.5194/essd-14-4681-2022",
            "URL": "https://doi.org/10.5194/essd-14-4681-2022",
            "title": ["Sample Article"],
            "abstract": "<jats:p>JATS-rendered fallback abstract.</jats:p>",
            "published": {"date-parts": [[2022, 12, 1]]},
        }
        item.update(overrides)
        return item

    def test_returns_none_without_doi(self):
        out = _crossref_item_to_work_kwargs(
            {"title": ["x"]}, self.source, self.event,
            fetch_abstract_from_publisher=False, abstract_session=None,
        )
        self.assertIsNone(out)

    def test_uses_crossref_abstract_when_publisher_disabled(self):
        out = _crossref_item_to_work_kwargs(
            self._item(), self.source, self.event,
            fetch_abstract_from_publisher=False, abstract_session=None,
        )
        self.assertEqual(out["doi"], "10.5194/essd-14-4681-2022")
        self.assertEqual(out["abstract"], "JATS-rendered fallback abstract.")
        self.assertEqual(out["publicationDate"], date(2022, 12, 1))
        self.assertEqual(out["status"], "h")

    @responses.activate
    def test_prefers_publisher_abstract_when_available(self):
        responses.add(
            responses.GET,
            "https://doi.org/10.5194/essd-14-4681-2022",
            body=SAMPLE_LANDING_HTML,
            content_type="text/html",
            status=200,
        )
        out = _crossref_item_to_work_kwargs(
            self._item(), self.source, self.event,
            fetch_abstract_from_publisher=True, abstract_session=None,
        )
        self.assertIn("urbanisation", out["abstract"].lower())
        # The literal "Abstract" lead should have been stripped.
        self.assertFalse(
            out["abstract"].lower().startswith("abstract"),
            f"Stale Abstract prefix: {out['abstract'][:40]!r}",
        )

    @responses.activate
    def test_falls_back_to_jats_when_landing_page_404s(self):
        responses.add(
            responses.GET,
            "https://doi.org/10.5194/essd-14-4681-2022",
            status=404,
        )
        out = _crossref_item_to_work_kwargs(
            self._item(), self.source, self.event,
            fetch_abstract_from_publisher=True, abstract_session=None,
        )
        self.assertEqual(out["abstract"], "JATS-rendered fallback abstract.")


class FetchCopernicusAbstractTests(TestCase):

    @responses.activate
    def test_uses_div_abstract_when_present(self):
        responses.add(
            responses.GET,
            "https://essd.copernicus.org/articles/14/4681/2022/",
            body=SAMPLE_LANDING_HTML,
            content_type="text/html",
            status=200,
        )
        out = fetch_copernicus_abstract(
            "https://essd.copernicus.org/articles/14/4681/2022/"
        )
        self.assertIn("urbanisation", out.lower())

    @responses.activate
    def test_falls_back_to_meta_when_div_absent(self):
        responses.add(
            responses.GET,
            "https://example.copernicus.org/article/",
            body=SAMPLE_LANDING_NO_ABSTRACT_DIV,
            content_type="text/html",
            status=200,
        )
        out = fetch_copernicus_abstract(
            "https://example.copernicus.org/article/"
        )
        self.assertEqual(out, "From the meta tag, fallback only.")

    @responses.activate
    def test_returns_none_on_http_error(self):
        responses.add(
            responses.GET,
            "https://example.copernicus.org/down/",
            status=503,
        )
        self.assertIsNone(fetch_copernicus_abstract(
            "https://example.copernicus.org/down/",
        ))

    def test_returns_none_for_empty_url(self):
        self.assertIsNone(fetch_copernicus_abstract(""))
        self.assertIsNone(fetch_copernicus_abstract(None))


class HarvestCrossrefPrefixEndToEndTests(TestCase):

    def setUp(self):
        from works.models import Collection
        collection, _ = Collection.objects.get_or_create(
            identifier='copernicus-publications',
            defaults={'name': 'Copernicus Publications', 'is_published': True},
        )
        self.source = Source.objects.create(
            name="Copernicus Crossref",
            url_field="https://api.crossref.org/works?filter=prefix:10.5194",
            source_type="crossref-prefix",
            collection=collection,
            harvest_interval_minutes=60 * 24 * 7,
            publisher_name="Copernicus Publications",
            is_oa=True,
            default_work_type="article",
        )

    def _crossref_response(self, items, next_cursor=None):
        return {
            "status": "ok",
            "message": {
                "total-results": len(items),
                "items": items,
                "next-cursor": next_cursor or "",
            },
        }

    @responses.activate
    def test_end_to_end_creates_works_with_publisher_abstracts(self):
        items = [
            {
                "DOI": "10.5194/essd-14-4681-2022",
                "URL": "https://doi.org/10.5194/essd-14-4681-2022",
                "title": ["Sample article 1"],
                "abstract": "<jats:p>fallback 1</jats:p>",
                "published-online": {"date-parts": [[2022, 12, 1]]},
            },
            {
                "DOI": "10.5194/essd-15-1-2023",
                "URL": "https://doi.org/10.5194/essd-15-1-2023",
                "title": ["Sample article 2"],
                "abstract": "<jats:p>fallback 2</jats:p>",
                "published-online": {"date-parts": [[2023, 1, 1]]},
            },
        ]
        responses.add(
            responses.GET,
            "https://api.crossref.org/works",
            json=self._crossref_response(items),
            status=200,
        )
        # Both DOI redirects return the same canonical landing page (close
        # enough to reality — each journal's landing page has the same
        # abstract structure).
        for item in items:
            responses.add(
                responses.GET,
                item["URL"],
                body=SAMPLE_LANDING_HTML,
                content_type="text/html",
                status=200,
            )

        harvest_crossref_prefix(self.source.id, fetch_abstract_from_publisher=True)

        works = Work.objects.filter(source=self.source).order_by("doi")
        self.assertEqual(works.count(), 2)
        for w in works:
            self.assertIn("urbanisation", w.abstract.lower())
            self.assertEqual(w.status, "h")

        event = HarvestingEvent.objects.filter(source=self.source).latest("started_at")
        self.assertEqual(event.status, "completed")

    @responses.activate
    def test_skips_existing_dois(self):
        # Pre-create one Work by DOI; the harvester should skip it.
        Work.objects.create(
            title="Pre-existing", doi="10.5194/already-here",
            source=self.source, status="p",
        )
        items = [
            {
                "DOI": "10.5194/already-here",
                "URL": "https://doi.org/10.5194/already-here",
                "title": ["dup"],
                "abstract": "<jats:p>x</jats:p>",
                "published": {"date-parts": [[2024, 1, 1]]},
            },
            {
                "DOI": "10.5194/new",
                "URL": "https://doi.org/10.5194/new",
                "title": ["new"],
                "abstract": "<jats:p>y</jats:p>",
                "published": {"date-parts": [[2024, 2, 1]]},
            },
        ]
        responses.add(
            responses.GET,
            "https://api.crossref.org/works",
            json=self._crossref_response(items),
            status=200,
        )
        # Only the "new" landing page will be hit (publisher fetch off).
        harvest_crossref_prefix(
            self.source.id, fetch_abstract_from_publisher=False,
        )
        # 1 pre-existing + 1 new = 2 total
        self.assertEqual(Work.objects.filter(source=self.source).count(), 2)
        self.assertTrue(Work.objects.filter(doi="10.5194/new").exists())

    @responses.activate
    def test_max_records_caps_processing(self):
        items = [
            {
                "DOI": f"10.5194/cap-{i}",
                "URL": f"https://doi.org/10.5194/cap-{i}",
                "title": [f"cap {i}"],
                "abstract": f"<jats:p>cap {i}</jats:p>",
                "published": {"date-parts": [[2024, 1, 1]]},
            }
            for i in range(5)
        ]
        responses.add(
            responses.GET,
            "https://api.crossref.org/works",
            json=self._crossref_response(items),
            status=200,
        )
        harvest_crossref_prefix(
            self.source.id, max_records=2,
            fetch_abstract_from_publisher=False,
        )
        self.assertEqual(Work.objects.filter(source=self.source).count(), 2)

    @responses.activate
    def test_journal_title_filter_passed_to_crossref(self):
        responses.add(
            responses.GET,
            "https://api.crossref.org/works",
            json=self._crossref_response([]),
            status=200,
        )
        harvest_crossref_prefix(
            self.source.id,
            source_titles=["Earth System Science Data"],
            fetch_abstract_from_publisher=False,
        )
        # Only one request was made; check its query string.
        self.assertEqual(len(responses.calls), 1)
        called = responses.calls[0].request.url
        self.assertIn("container-title%3AEarth+System+Science+Data", called.replace(":", "%3A"))
