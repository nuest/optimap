# SPDX-FileCopyrightText: 2026 OPTIMETA and KOMET projects <https://projects.tib.eu/komet>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Extract EO4GEO BoK concept codes from AGILE GIScience Series full-text PDFs.

AGILE GISS papers include a "BoK Concepts." section on the first page (right
after the abstract). Three formats are observed in the wild:

    [TA12-6] EO for infrastructure; [GS4-3b] Citizens and VGI
    image processing -> image understanding -> visual interpretation
    Geocomputation, Geospatial Data.

DOI-to-PDF-URL mapping:
    10.5194/agile-giss-{vol}-{art}-{year}
    -> https://agile-giss.copernicus.org/articles/{vol}/{art}/{year}/
       agile-giss-{vol}-{art}-{year}.pdf
"""

from __future__ import annotations

import contextlib
import logging
import os
import re
import tempfile
from typing import TYPE_CHECKING

import requests
from django.conf import settings
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from works.bok.client import is_known, match_text_to_codes

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

_AGILE_DOI_RE = re.compile(r"^10\.5194/agile-giss-(\d+)-(\d+)-(\d{4})$", re.IGNORECASE)

# "BoK Concepts." or "BoK Concepts:" up to the next blank line or a capitalised
# section label (a word ending in a period, e.g. "Keywords." or "Abstract.").
# The header match uses an inline (?i:...) flag so only that part is
# case-insensitive; the stop condition must stay case-sensitive — applying
# re.IGNORECASE to the whole pattern would make [A-Z] match lowercase letters
# and cause word-wrapped lines like "\ndata models" or "\nGeostatistics,"
# to falsely trigger the stop condition.
_BOK_SECTION_RE = re.compile(
    r"(?i:BoK Concepts[.:])\s*(.+?)(?=\n\s*\n|\n[A-Z][a-zA-Z]+\.|\Z)",
    re.DOTALL,
)

# Bracketed BoK codes: [TA12-6], [GS4-3b], [AM10], …
_BRACKET_CODE_RE = re.compile(r"\[([A-Za-z0-9_-]{1,32})\]")

# Parenthesised codes: (TA12-2), (GS3-4) — also covers "AM(AM8)" parent-prefix
# format (the inner part is extracted). Code must begin with a letter.
_PAREN_CODE_RE = re.compile(r"\(([A-Za-z][A-Za-z0-9_-]{0,31})\)")

# Codes split across a line break by hyphenation: "TA12-\n2" → "TA12-2"
_LINE_BREAK_IN_CODE_RE = re.compile(r"([A-Za-z0-9])-\n([A-Za-z0-9])")

_PDF_HTTP_TIMEOUT = 60
_PDF_RETRY_TOTAL = 3


def agile_giss_doi_to_pdf_url(doi: str) -> str | None:
    """Return the Copernicus PDF download URL for an AGILE GISS DOI, or None."""
    m = _AGILE_DOI_RE.match((doi or "").strip())
    if not m:
        return None
    vol, art, year = m.group(1), m.group(2), m.group(3)
    return f"https://agile-giss.copernicus.org/articles/{vol}/{art}/{year}/agile-giss-{vol}-{art}-{year}.pdf"


def _agile_pdf_session() -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=_PDF_RETRY_TOTAL,
        connect=_PDF_RETRY_TOTAL,
        read=_PDF_RETRY_TOTAL,
        backoff_factor=1.5,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset(["GET"]),
        respect_retry_after_header=True,
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    session.headers.update(
        {
            "User-Agent": settings.OPTIMAP_USER_AGENT,
            "Accept": "application/pdf, */*",
        }
    )
    return session


def _find_bok_section(text: str) -> str | None:
    """Return the raw text of the BoK Concepts section, or None."""
    m = _BOK_SECTION_RE.search(text)
    return m.group(1).strip() if m else None


def _parse_bok_section(section: str) -> list[str]:
    """Extract validated BoK concept codes from the section text.

    Handles all observed real-world formats:
      - Bracketed:             [TA12-6] Name; [GS4-3b] Name
      - Parenthesised:         Name (TA12-2), Name (GS3-4)
      - Parent-prefixed paren: AM(AM8), GD(GD4)
      - Bare codes:            IP, DM.
      - Code split by newline: Name (TA12-\\n2)  →  normalised to (TA12-2)
      - Arrow names:           image processing -> image understanding
      - Comma/semicolon names: Geocomputation, Geospatial Data.

    Strategy:
        1. Pre-process: join codes split across line breaks.
        2. Collect all literal codes from brackets [CODE] and parentheses (CODE).
        3. Scan comma/semicolon tokens for bare codes directly known to the BoK.
        4. If nothing found, fall back to name-based lookup (arrow or comma list).
    """
    # 1. Join codes hyphenated across a line break ("TA12-\n2" → "TA12-2")
    section = _LINE_BREAK_IN_CODE_RE.sub(r"\1-\2", section)

    seen: set[str] = set()
    out: list[str] = []

    def _accept(code: str) -> None:
        if code and code not in seen and is_known(code):
            seen.add(code)
            out.append(code)

    # 2. Bracketed [CODE] and parenthesised (CODE)
    for code in _BRACKET_CODE_RE.findall(section):
        _accept(code)
    for code in _PAREN_CODE_RE.findall(section):
        _accept(code)

    # 3. Bare codes from comma/semicolon tokens (e.g. "IP, DM.")
    for part in re.split(r"[,;]", section):
        _accept(part.strip().rstrip(".").strip())

    if out:
        return out

    # 4. Name-matching fallback
    if "→" in section or "->" in section:
        parts = re.split(r"→|->", section)
    else:
        parts = re.split(r"[,;]", section)
    return match_text_to_codes([p.strip().rstrip(".") for p in parts])


def extract_bok_from_agile_pdf(doi: str, session: requests.Session | None = None) -> list[str]:
    """Download the AGILE GISS PDF for *doi* and return validated BoK concept codes.

    Returns an empty list when:
    - The DOI is not an AGILE GISS DOI.
    - The PDF cannot be fetched or parsed.
    - No BoK Concepts section is found.
    - No codes can be resolved from the section.

    Never raises — all errors are logged at WARNING level.
    """
    pdf_url = agile_giss_doi_to_pdf_url(doi)
    if not pdf_url:
        return []

    try:
        _session = session or _agile_pdf_session()
        resp = _session.get(pdf_url, timeout=_PDF_HTTP_TIMEOUT)
        if not resp.ok:
            logger.warning("PDF fetch failed for %s: HTTP %s", pdf_url, resp.status_code)
            return []

        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=True) as tmp:
            tmp.write(resp.content)
            tmp.flush()
            return _extract_from_file(tmp.name, doi=doi, pdf_url=pdf_url)

    except Exception as exc:
        logger.warning("BoK PDF extraction failed for %s (%s): %s", doi, pdf_url, exc)
        return []


@contextlib.contextmanager
def _suppress_stderr():
    """Redirect stderr at the OS fd level to /dev/null.

    pdf_oxide's Rust layer prints "Dictionary used where Stream expected"
    diagnostics directly to fd 2 for some older PDFs. These are benign parse
    warnings that produce empty streams, not errors — but they flood the log.
    Python's sys.stderr redirect doesn't reach the Rust layer, so we dup2.
    """
    devnull = os.open(os.devnull, os.O_WRONLY)
    saved_fd = os.dup(2)
    try:
        os.dup2(devnull, 2)
        yield
    finally:
        os.dup2(saved_fd, 2)
        os.close(saved_fd)
        os.close(devnull)


def _extract_from_file(path: str, doi: str = "", pdf_url: str = "") -> list[str]:
    """Extract BoK codes from a local PDF file path."""
    try:
        import pdf_oxide
    except ImportError:
        logger.warning("pdf_oxide not installed — cannot extract BoK from PDF")
        return []

    try:
        with _suppress_stderr():
            doc = pdf_oxide.PdfDocument(path)
            pages_to_scan = min(3, doc.page_count)
            full_text = "\n".join(doc.extract_text(p) for p in range(pages_to_scan))
    except Exception as exc:
        logger.warning("pdf_oxide failed to parse PDF for %s: %s", doi or path, exc)
        return []

    section = _find_bok_section(full_text)
    if section is None:
        logger.debug("No BoK Concepts section found in PDF for %s", doi or path)
        return []

    codes = _parse_bok_section(section)
    logger.info(
        "BoK PDF extraction for %s: section=%r codes=%s",
        doi or pdf_url,
        section[:120],
        codes,
    )
    return codes
