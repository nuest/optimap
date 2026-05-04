# SPDX-FileCopyrightText: 2026 OPTIMETA and KOMET projects <https://projects.tib.eu/komet>
# SPDX-License-Identifier: GPL-3.0-or-later

"""HTTP session factories and response sniffers shared by every harvester."""

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


# OAI-PMH ---------------------------------------------------------------------

OAI_HTTP_TIMEOUT = 30  # seconds; per-request, applies to both connect and read
OAI_RETRY_TOTAL = 3
OAI_USER_AGENT = "OPTIMAP-harvester/1.0 (+https://optimap.science)"


def _oai_session() -> requests.Session:
    """`requests.Session` configured with retries for transient errors and a
    descriptive User-Agent so upstream operators can identify our traffic.
    Retries cover GET only; 4xx (other than 429) are not retried because they
    almost always indicate a permanent problem (bad URL, removed set)."""
    session = requests.Session()
    retry = Retry(
        total=OAI_RETRY_TOTAL,
        connect=OAI_RETRY_TOTAL,
        read=OAI_RETRY_TOTAL,
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
        "User-Agent": OAI_USER_AGENT,
        "Accept": "text/xml, application/xml, */*",
    })
    return session


def _looks_like_oai_xml(body: bytes) -> bool:
    """Cheap content sniff so we fail fast and clearly when an upstream
    'helpfully' returns an HTML 200 error page instead of an OAI-PMH response."""
    if not body:
        return False
    head = body.lstrip()[:512].lower()
    if head.startswith(b"<?xml"):
        return True
    return b"<oai-pmh" in head


def _short_body(resp: requests.Response, n: int = 240) -> str:
    """Trim a response body for use in error messages."""
    text = resp.text or ""
    text = " ".join(text.split())
    if len(text) > n:
        return text[:n] + "…"
    return text


# Crossref --------------------------------------------------------------------

CROSSREF_API_URL = "https://api.crossref.org/works"
# Polite-pool User-Agent — Crossref rate-limits anonymous traffic.
CROSSREF_USER_AGENT = (
    "OPTIMAP/1.0 (https://github.com/GeoinformationSystems/optimap; "
    "mailto:info@optimap.science)"
)
CROSSREF_HTTP_TIMEOUT = 60
CROSSREF_PAGE_ROWS = 100


def _crossref_session():
    """Return a requests.Session preconfigured with retries + UA."""
    session = requests.Session()
    retry = Retry(
        total=4,
        backoff_factor=2,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=frozenset(["GET"]),
    )
    session.mount("https://", HTTPAdapter(max_retries=retry))
    session.headers.update({
        "User-Agent": CROSSREF_USER_AGENT,
        "Accept": "application/json",
    })
    return session


# Mountain Wetlands Repository (MaRESS) ---------------------------------------

MWR_PAGE_SIZE = 500
MWR_HTTP_TIMEOUT = 60  # seconds; MaRESS responses can be hefty (study_sites embed)


def _mwr_session() -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=3, connect=3, read=3,
        backoff_factor=1.5,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset(["GET"]),
        respect_retry_after_header=True,
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    session.headers.update({"User-Agent": OAI_USER_AGENT, "Accept": "application/json"})
    return session
