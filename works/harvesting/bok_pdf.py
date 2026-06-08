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

_AGILE_DOI_RE = re.compile(
    r"^10\.5194/agile-giss-(\d+)-(\d+)-(\d{4})$", re.IGNORECASE
)

# "BoK Concepts." (with or without trailing space) up to the next blank line or
# capitalised section header. Handles multi-line wraps within the section.
_BOK_SECTION_RE = re.compile(
    r"BoK Concepts\.\s*(.+?)(?=\n\s*\n|\n[A-Z][a-zA-Z]|\Z)",
    re.IGNORECASE | re.DOTALL,
)

# Bracketed BoK codes: [TA12-6], [GS4-3b], [AM10], …
_BRACKET_CODE_RE = re.compile(r"\[([A-Za-z0-9_-]{1,32})\]")

_PDF_HTTP_TIMEOUT = 60
_PDF_RETRY_TOTAL = 3


def agile_giss_doi_to_pdf_url(doi: str) -> str | None:
    """Return the Copernicus PDF download URL for an AGILE GISS DOI, or None."""
    m = _AGILE_DOI_RE.match((doi or "").strip())
    if not m:
        return None
    vol, art, year = m.group(1), m.group(2), m.group(3)
    return (
        f"https://agile-giss.copernicus.org/articles/{vol}/{art}/{year}/"
        f"agile-giss-{vol}-{art}-{year}.pdf"
    )


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
    session.headers.update({
        "User-Agent": settings.OPTIMAP_USER_AGENT,
        "Accept": "application/pdf, */*",
    })
    return session


def _find_bok_section(text: str) -> str | None:
    """Return the raw text of the BoK Concepts section, or None."""
    m = _BOK_SECTION_RE.search(text)
    return m.group(1).strip() if m else None


def _parse_bok_section(section: str) -> list[str]:
    """Extract validated BoK concept codes from the section text.

    Priority:
        1. Bracketed codes [XX-Y] — taken as literal codes.
        2. Arrow-separated names (→ or ->) — each segment looked up by name.
        3. Comma/semicolon-separated names — looked up by name.
    """
    # 1. Bracketed codes
    bracketed = _BRACKET_CODE_RE.findall(section)
    if bracketed:
        seen: set[str] = set()
        out: list[str] = []
        for code in bracketed:
            if code not in seen and is_known(code):
                seen.add(code)
                out.append(code)
        return out

    # 2. Arrow notation (both → and ->)
    if "→" in section or "->" in section:
        parts = re.split(r"→|->", section)
        return match_text_to_codes([p.strip().rstrip(".") for p in parts])

    # 3. Comma / semicolon list
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
        doi or pdf_url, section[:120], codes,
    )
    return codes
