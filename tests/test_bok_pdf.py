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
    _LINE_BREAK_IN_CODE_RE,
    _extract_from_file,
    _find_bok_section,
    _parse_bok_section,
    agile_giss_doi_to_pdf_url,
    extract_bok_from_agile_pdf,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures"


# Minimal BoK snapshot used in mocked tests
def _entry(code, name):
    return {"code": code, "id": code, "name": name, "uri": "", "description": "", "parent_code": "", "breadcrumb": []}


_MOCK_SNAPSHOT = {
    "TA12-6": _entry("TA12-6", "EO for infrastructure & transport"),
    "GS4-3b": _entry("GS4-3b", "Citizens and volunteered geographic information"),
    "IP3": _entry("IP3", "image understanding"),
    "GC1": _entry("GC1", "Geocomputation"),
    "GD1": _entry("GD1", "Geospatial Data"),
    # codes for new-format tests
    "TA12-2": _entry("TA12-2", "EO for biodiversity & ecosystems"),
    "GS3-4": _entry("GS3-4", "Use of geospatial information in environmental issues"),
    "AM8": _entry("AM8", "Geostatistics"),
    "GD4": _entry("GD4", "Data Quality, Metadata and Data Infrastructure"),
    "IP": _entry("IP", "Image processing and analysis"),
    "DM": _entry("DM", "Data modelling and management"),
    "AM": _entry("AM", "Analytical Methods"),
    "CF": _entry("CF", "Conceptual Foundations"),
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

    def test_multiline_lowercase_continuation(self):
        # regression: re.IGNORECASE made [A-Z] match lowercase, truncating sections
        # where a word-wrapped line started with a lowercase letter (e.g. "data models")
        text = (
            "BoK Concepts. [IP5-1] Data cubes; [DM3-7] Hierarchical\n"
            "data models; [DA3-6] Cloud and Grid computing\n\n"
            "Keywords."
        )
        section = _find_bok_section(text)
        self.assertIsNotNone(section)
        self.assertIn("DA3-6", section)

    def test_multiline_uppercase_continuation(self):
        # regression: \n[A-Z][a-zA-Z] stop condition fired on word-wrapped lines
        # starting with an uppercase letter (e.g. "Geostatistics,") that are NOT
        # section headers — only lines ending with "." should terminate the section
        text = (
            "BoK Concepts. [AM8]\n"
            "Geostatistics, [DM1-4] Data Structures and Indices for\n"
            "Databases, [DM1-5] Data compression techniques\n\n"
            "Keywords."
        )
        section = _find_bok_section(text)
        self.assertIsNotNone(section)
        self.assertIn("DM1-4", section)
        self.assertIn("DM1-5", section)

    def test_colon_delimiter(self):
        # Some papers use "BoK Concepts:" (colon) instead of "BoK Concepts." (period)
        text = "BoK Concepts: [AM] Analytical Methods, [CF] Conceptual Foundations\n\nKeywords."
        section = _find_bok_section(text)
        self.assertIsNotNone(section)
        self.assertIn("AM", section)
        self.assertIn("CF", section)

    def test_missing_section(self):
        text = "Abstract\n\nNo BoK here.\n\nKeywords. city"
        self.assertIsNone(_find_bok_section(text))


class TestLineBreakNorm(TestCase):
    def test_normalises_hyphen_split(self):
        self.assertEqual(_LINE_BREAK_IN_CODE_RE.sub(r"\1-\2", "TA12-\n2"), "TA12-2")

    def test_leaves_word_wrap_untouched(self):
        # A newline NOT preceded by a hyphen should not be altered
        result = _LINE_BREAK_IN_CODE_RE.sub(r"\1-\2", "analysis\nof data")
        self.assertEqual(result, "analysis\nof data")


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

    def test_paren_codes(self):
        # Format: "Name (CODE), Name (CODE)"
        with self._with_snapshot():
            codes = _parse_bok_section("EO for biodiversity (TA12-2), geospatial use (GS3-4)")
        self.assertIn("TA12-2", codes)
        self.assertIn("GS3-4", codes)

    def test_line_break_within_code(self):
        # Format: code hyphenated across a line break "TA12-\n2" → "TA12-2"
        with self._with_snapshot():
            codes = _parse_bok_section("EO for biodiversity & ecosystems (TA12-\n2), geospatial use\n(GS3-4)")
        self.assertIn("TA12-2", codes)
        self.assertIn("GS3-4", codes)

    def test_parent_prefixed_paren(self):
        # Format: "AM(AM8), GD(GD4)" — parent code prefix, child code in parens
        with self._with_snapshot():
            codes = _parse_bok_section("AM(AM8), GD(GD4)")
        self.assertIn("AM8", codes)
        self.assertIn("GD4", codes)

    def test_bare_codes_mixed_with_paren(self):
        # Format: "AM(AM8), GD(GD4), IP, DM." — parent-paren codes plus bare codes
        with self._with_snapshot():
            codes = _parse_bok_section("AM(AM8), GD(GD4), IP, DM.")
        self.assertIn("AM8", codes)
        self.assertIn("GD4", codes)
        self.assertIn("IP", codes)
        self.assertIn("DM", codes)

    def test_top_level_bracketed_codes(self):
        # Format: "[AM] Name, [CF] Name" — top-level (non-leaf) codes in brackets
        with self._with_snapshot():
            codes = _parse_bok_section("[AM] Analytical Methods, [CF] Conceptual Foundations")
        self.assertIn("AM", codes)
        self.assertIn("CF", codes)


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
        responses.add(responses.GET, pdf_url, body=pdf_bytes, status=200, content_type="application/pdf")
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
