# SPDX-FileCopyrightText: 2026 OPTIMETA and KOMET projects <https://projects.tib.eu/komet>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Normalise OpenAlex `primary_location` + `locations[]` into `Work.locations`.

OpenAlex assigns one work id to a scholarly work and lists every hosting copy
(journal version, preprint, repository copies) under ``locations[]``, with
``primary_location`` being its canonical pick. This module is the single
producer of OPTIMAP's ``Work.locations`` JSON so the enrichment path
(``openalex_matcher``) and the OpenAlex-as-source path (``openalex_source``)
emit identical shapes. Every entry is credited to OpenAlex.
"""

from django.utils import timezone

OPENALEX_LOCATION_CREDIT = "openalex"


def _normalize_source(source) -> dict | None:
    """Trim an OpenAlex location ``source`` object to the fields we keep."""
    if not isinstance(source, dict):
        return None
    out = {
        "openalex_id": source.get("id"),
        "display_name": source.get("display_name"),
        "type": source.get("type"),
        "issn_l": source.get("issn_l"),
    }
    # Drop all-empty source objects (some repository locations carry none).
    if not any(out.values()):
        return None
    return {k: v for k, v in out.items() if v is not None}


def _normalize_location(loc, *, is_primary: bool, retrieved_at: str) -> dict | None:
    """Normalise one OpenAlex location dict; return ``None`` if it has no URL."""
    if not isinstance(loc, dict):
        return None
    landing_page_url = loc.get("landing_page_url")
    pdf_url = loc.get("pdf_url")
    if not landing_page_url and not pdf_url:
        return None
    entry = {
        "credit": OPENALEX_LOCATION_CREDIT,
        "retrieved_at": retrieved_at,
        "is_primary": is_primary,
        "version": loc.get("version"),
        "landing_page_url": landing_page_url,
        "pdf_url": pdf_url,
        "is_oa": loc.get("is_oa"),
        "license": loc.get("license"),
        "doi": loc.get("doi"),
        "source": _normalize_source(loc.get("source")),
    }
    return {k: v for k, v in entry.items() if v is not None}


def _location_key(entry: dict):
    """Identity key for deduping locations (landing URL, else pdf URL, else DOI)."""
    return entry.get("landing_page_url") or entry.get("pdf_url") or entry.get("doi")


def build_locations(payload) -> list[dict]:
    """Build the ``Work.locations`` list from an OpenAlex work payload.

    Merges ``primary_location`` and ``locations[]``, marks exactly the primary
    entry ``is_primary=True``, and dedupes by landing-page URL. Returns ``[]``
    for an empty/invalid payload so callers can treat the result as fill-if-empty.
    """
    if not isinstance(payload, dict):
        return []

    retrieved_at = timezone.now().isoformat()
    primary = payload.get("primary_location")
    primary_key = None
    result: list[dict] = []
    seen = set()

    if isinstance(primary, dict):
        entry = _normalize_location(primary, is_primary=True, retrieved_at=retrieved_at)
        if entry is not None:
            primary_key = _location_key(entry)
            result.append(entry)
            seen.add(primary_key)

    for loc in payload.get("locations") or []:
        entry = _normalize_location(loc, is_primary=False, retrieved_at=retrieved_at)
        if entry is None:
            continue
        key = _location_key(entry)
        if key in seen:
            continue
        seen.add(key)
        result.append(entry)

    return result
