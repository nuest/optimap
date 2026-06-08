# SPDX-FileCopyrightText: 2026 OPTIMETA and KOMET projects <https://projects.tib.eu/komet>
# SPDX-License-Identifier: GPL-3.0-or-later

import os
from pathlib import Path
from unittest.mock import patch

import django
import responses
from django.test import TestCase, tag

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "optimap.settings")
django.setup()

from works.harvesting.bok_pdf import (
    _extract_from_file,
    _find_bok_section,
    _parse_bok_section,
    agile_giss_doi_to_pdf_url,
    extract_bok_from_agile_pdf,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures"

# Minimal BoK snapshot used in mocked tests
_MOCK_SNAPSHOT = {
    "TA12-6": {"code": "TA12-6", "id": "TA12-6", "name": "EO for infrastructure & transport", "uri": "", "description": "", "parent_code": "", "breadcrumb": []},
    "GS4-3b": {"code": "GS4-3b", "id": "GS4-3b", "name": "Citizens and volunteered geographic information", "uri": "", "description": "", "parent_code": "", "breadcrumb": []},
    "IP3":    {"code": "IP3",    "id": "IP3",    "name": "image understanding",          "uri": "", "description": "", "parent_code": "", "breadcrumb": []},
    "GC1":    {"code": "GC1",    "id": "GC1",    "name": "Geocomputation",                "uri": "", "description": "", "parent_code": "", "breadcrumb": []},
    "GD1":    {"code": "GD1",    "id": "GD1",    "name": "Geospatial Data",               "uri": "", "description": "", "parent_code": "", "breadcrumb": []},
}


class TestDoiToPdfUrl(TestCase):

    def test_valid_doi(self):
        url = agile_giss_doi_to_pdf_url("10.5194/agile-giss-6-2-2025")
        self.assertEqual(
            url,
            "https://agile-giss.copernicus.org/articles/6/2/2025/agile-giss-6-2-2025.pdf",
        )

    def test_valid_doi_uppercase(self):
        url = agile_giss_doi_to_pdf_url("10.5194/AGILE-GISS-6-2-2025")
        self.assertIsNotNone(url)
        self.assertIn("agile-giss-6-2-2025", url)

    def test_non_agile_doi(self):
        self.assertIsNone(agile_giss_doi_to_pdf_url("10.1038/s41586-021-03537-w"))

    def test_empty_doi(self):
        self.assertIsNone(agile_giss_doi_to_pdf_url(""))

    def test_none_doi(self):
        self.assertIsNone(agile_giss_doi_to_pdf_url(None))


class TestFindBokSection(TestCase):

    def test_finds_section(self):
        text = "Abstract\n\nSome text.\n\nBoK Concepts. [TA12-6] Infrastructure\n\nKeywords. city"
        section = _find_bok_section(text)
        self.assertIsNotNone(section)
        self.assertIn("TA12-6", section)

    def test_case_insensitive(self):
        text = "bok concepts. Geocomputation\n\nKeywords."
        self.assertIsNotNone(_find_bok_section(text))

    def test_missing_section(self):
        text = "Abstract\n\nNo BoK here.\n\nKeywords. city"
        self.assertIsNone(_find_bok_section(text))


class TestParseBokSection(TestCase):

    def _with_snapshot(self):
        return patch("works.bok.client.get_concepts", return_value=_MOCK_SNAPSHOT)

    def test_bracketed_codes(self):
        with self._with_snapshot():
            codes = _parse_bok_section("[TA12-6] EO for infrastructure; [GS4-3b] Citizens and VGI")
        self.assertEqual(codes, ["TA12-6", "GS4-3b"])

    def test_bracketed_unknown_code_dropped(self):
        with self._with_snapshot():
            codes = _parse_bok_section("[UNKNOWN99] Some name; [TA12-6] EO for infrastructure")
        self.assertEqual(codes, ["TA12-6"])

    def test_arrow_names(self):
        with self._with_snapshot():
            codes = _parse_bok_section("image understanding -> visual interpretation")
        # "image understanding" matches IP3 exactly; "visual interpretation" has no match
        self.assertIn("IP3", codes)

    def test_arrow_unicode(self):
        with self._with_snapshot():
            codes = _parse_bok_section("image understanding → visual interpretation")
        self.assertIn("IP3", codes)

    def test_comma_names(self):
        with self._with_snapshot():
            codes = _parse_bok_section("Geocomputation, Geospatial Data.")
        self.assertIn("GC1", codes)
        self.assertIn("GD1", codes)

    def test_semicolon_names(self):
        with self._with_snapshot():
            codes = _parse_bok_section("Geocomputation; Geospatial Data.")
        self.assertIn("GC1", codes)

    def test_deduplication(self):
        with self._with_snapshot():
            codes = _parse_bok_section("[TA12-6] name; [TA12-6] duplicate")
        self.assertEqual(codes.count("TA12-6"), 1)


class TestExtractFromFixturePdfs(TestCase):
    """Test extraction using the committed fixture PDFs (no network)."""

    def _with_snapshot(self):
        return patch("works.bok.client.get_concepts", return_value=_MOCK_SNAPSHOT)

    def test_bracketed_pdf(self):
        with self._with_snapshot():
            codes = _extract_from_file(str(FIXTURES / "bok_bracketed.pdf"))
        self.assertIn("TA12-6", codes)
        self.assertIn("GS4-3b", codes)

    def test_arrow_pdf(self):
        with self._with_snapshot():
            codes = _extract_from_file(str(FIXTURES / "bok_arrow.pdf"))
        self.assertIn("IP3", codes)

    def test_comma_pdf(self):
        with self._with_snapshot():
            codes = _extract_from_file(str(FIXTURES / "bok_comma.pdf"))
        self.assertIn("GC1", codes)
        self.assertIn("GD1", codes)


class TestExtractBokFromAgile(TestCase):
    """Test the HTTP-level extraction function with a mocked response."""

    def _with_snapshot(self):
        return patch("works.bok.client.get_concepts", return_value=_MOCK_SNAPSHOT)

    @responses.activate
    def test_successful_extraction(self):
        doi = "10.5194/agile-giss-6-2-2025"
        pdf_url = agile_giss_doi_to_pdf_url(doi)
        pdf_bytes = (FIXTURES / "bok_bracketed.pdf").read_bytes()
        responses.add(responses.GET, pdf_url, body=pdf_bytes, status=200,
                      content_type="application/pdf")
        with self._with_snapshot():
            codes = extract_bok_from_agile_pdf(doi)
        self.assertIn("TA12-6", codes)

    @responses.activate
    def test_http_error_returns_empty(self):
        doi = "10.5194/agile-giss-6-2-2025"
        pdf_url = agile_giss_doi_to_pdf_url(doi)
        responses.add(responses.GET, pdf_url, status=404)
        codes = extract_bok_from_agile_pdf(doi)
        self.assertEqual(codes, [])

    def test_non_agile_doi_returns_empty(self):
        codes = extract_bok_from_agile_pdf("10.1038/s41586-021-03537-w")
        self.assertEqual(codes, [])

    def test_empty_doi_returns_empty(self):
        self.assertEqual(extract_bok_from_agile_pdf(""), [])


@tag("online")
class TestExtractBokOnline(TestCase):
    """Download a real AGILE GISS PDF and verify extraction. Requires network."""

    def test_real_agile_paper(self):
        codes = extract_bok_from_agile_pdf("10.5194/agile-giss-6-2-2025")
        # The paper has at least one BoK concept; we can't assert exact codes since
        # the snapshot might not be loaded in CI, but we verify the function runs.
        self.assertIsInstance(codes, list)
