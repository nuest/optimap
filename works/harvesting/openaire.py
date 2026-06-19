# SPDX-FileCopyrightText: 2026 OPTIMETA and KOMET projects <https://projects.tib.eu/komet>
# SPDX-License-Identifier: GPL-3.0-or-later

"""OpenAIRE enrichment — a second metadata source besides OpenAlex.

OpenAIRE's Graph API carries abstracts (and other metadata) for works whose
harvest origin did not supply them — notably the AGILE Springer LNCS chapters
(DOI prefix ``10.1007/978-…``) for which Crossref has no abstract and the
publisher landing page is not scraped.

A single DOI is resolved via ``GET <OPENAIRE_API_URL>?pid=<doi>`` which returns
``{"header": {...}, "results": [ {...} ]}``; the abstract lives in
``results[0].descriptions[]``.

This module exposes:
- ``fetch_openaire_record`` / ``build_openaire_fields`` — pure lookup + extraction.
- ``enrich_work_from_openaire`` — the single per-work enricher, reused by both the
  live post-harvest sweep and the ``enrich_openaire`` backfill command. It applies
  the fill-if-empty policy (``works.harvesting.enrichment.apply_enrichment``) and
  records every decision in ``Work.provenance`` (``metadata_sources``, an
  ``openaire_enrich`` event, and an ``openaire_match`` block).
- ``enrich_event_from_openaire`` — the async sweep enqueued by ``complete_harvest``.

Both ``enrich_*`` callables are re-exported from ``works.tasks`` so Django-Q
dotted-path schedules resolve.
"""

import logging
import time

import requests
from django.conf import settings
from django.db.models import Q

from works.harvesting.enrichment import apply_enrichment
from works.harvesting.sessions import (
    OPENAIRE_API_URL,
    OPENAIRE_HTTP_TIMEOUT,
    OPENAIRE_TOKEN_EXCHANGE_URL,
    OPENAIRE_USER_AGENT,
    _openaire_session,
)
from works.models import HarvestingEvent
from works.utils.provenance import append_event

logger = logging.getLogger(__name__)

# OpenAIRE attaches automated classifications under these subject schemes; they
# are not free-text keywords and would pollute Work.keywords, so we drop them.
_AUTOMATED_SUBJECT_SCHEMES = {"sdg", "fos"}

# Work fields OpenAIRE may fill (fill-if-empty). `type` is excluded (OpenAIRE's
# coarse "publication"/"dataset" is less useful than the source default);
# `language` has no Work model field.
ENRICHABLE_FIELDS = ("abstract", "keywords", "authors")


def get_openaire_access_token():
    """Return a valid OpenAIRE access token, or ``None``.

    Backed by the refresh token stored in the ``ServiceToken`` table (rotated by
    staff in the Django admin). Returns the cached access token while it is still
    valid; otherwise exchanges the refresh token for a fresh one via
    ``GET OPENAIRE_TOKEN_EXCHANGE_URL?refreshToken=...`` (the access token is
    valid ~1h) and caches it on the row. Returns ``None`` when no refresh token
    is configured or the exchange fails — callers then fall back to the static
    ``OPTIMAP_OPENAIRE_TOKEN`` or anonymous access.

    Uses a plain ``requests.get`` (not ``_openaire_session``) to avoid recursing
    back into bearer-token resolution.
    """
    from works.models import ServiceToken

    token_row = ServiceToken.objects.filter(service=ServiceToken.OPENAIRE).first()
    if token_row is None or not token_row.refresh_token:
        return None
    if token_row.access_token_valid():
        return token_row.access_token

    try:
        resp = requests.get(
            OPENAIRE_TOKEN_EXCHANGE_URL,
            params={"refreshToken": token_row.refresh_token},
            headers={"User-Agent": OPENAIRE_USER_AGENT, "Accept": "application/json"},
            timeout=OPENAIRE_HTTP_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
    except (requests.RequestException, ValueError) as exc:
        logger.warning("OpenAIRE token exchange failed: %s", exc)
        return None

    access_token = data.get("access_token") if isinstance(data, dict) else None
    if not access_token:
        logger.warning("OpenAIRE token exchange returned no access_token")
        return None

    ttl = data.get("expires_in") if isinstance(data, dict) else None
    try:
        ttl = int(ttl)
    except (TypeError, ValueError):
        ttl = settings.OPTIMAP_OPENAIRE_ACCESS_TOKEN_TTL
    token_row.store_access_token(access_token, ttl)
    logger.info("Exchanged OpenAIRE refresh token for a new access token (ttl=%ss).", ttl)
    return access_token


def fetch_openaire_record(doi, session=None):
    """Look up a single research product by DOI. Returns the record dict or None.

    Tolerant of network and JSON errors (logged, returns None) so enrichment
    never aborts a harvest or backfill.
    """
    if not doi:
        return None
    owns_session = session is None
    session = session or _openaire_session()
    try:
        resp = session.get(OPENAIRE_API_URL, params={"pid": doi}, timeout=OPENAIRE_HTTP_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
    except (requests.RequestException, ValueError) as exc:
        logger.warning("OpenAIRE lookup failed for DOI %s: %s", doi, exc)
        return None
    finally:
        if owns_session:
            session.close()

    results = data.get("results") or []
    if not results:
        return None
    return results[0]


def _best_description(descriptions):
    """Return the longest non-empty description (the fullest abstract)."""
    if not descriptions:
        return None
    candidates = [d.strip() for d in descriptions if isinstance(d, str) and d.strip()]
    if not candidates:
        return None
    return max(candidates, key=len)


def _keywords_from_subjects(subjects):
    """Return free-text keyword values, dropping automated classification schemes."""
    if not subjects:
        return []
    keywords = []
    for entry in subjects:
        subject = (entry or {}).get("subject") or {}
        scheme = (subject.get("scheme") or "").strip().lower()
        value = (subject.get("value") or "").strip()
        if not value or scheme in _AUTOMATED_SUBJECT_SCHEMES:
            continue
        if value not in keywords:
            keywords.append(value)
    return keywords


def build_openaire_fields(record):
    """Extract enrichment candidates from an OpenAIRE record (pure, no DB).

    Returns ``{field: value}`` for the subset of ``ENRICHABLE_FIELDS`` that the
    record provides; empty values are omitted so ``apply_enrichment`` skips them.
    """
    if not record:
        return {}

    candidates = {}

    abstract = _best_description(record.get("descriptions"))
    if abstract:
        candidates["abstract"] = abstract

    keywords = _keywords_from_subjects(record.get("subjects"))
    if keywords:
        candidates["keywords"] = keywords

    authors = [a["fullName"].strip() for a in (record.get("authors") or []) if (a or {}).get("fullName")]
    if authors:
        candidates["authors"] = authors

    return candidates


def enrich_work_from_openaire(work, *, session=None, save=True):
    """Enrich a single Work from OpenAIRE (fill-if-empty). Returns True if changed.

    Records the outcome in ``work.provenance`` regardless of whether anything was
    filled: an ``openaire_match`` block (``status`` matched/none) plus, on a match,
    an ``openaire_enrich`` event listing ``fields_filled`` and
    ``fields_offered_not_applied`` (the conflicts resolved in favour of the
    existing value).
    """
    doi = (work.doi or "").strip()
    record = fetch_openaire_record(doi, session=session) if doi else None

    if not record:
        provenance = work.provenance if isinstance(work.provenance, dict) else {}
        provenance["openaire_match"] = {"status": "none", "num_found": 0}
        work.provenance = provenance
        if save:
            work.save(update_fields=["provenance", "lastUpdate"])
        return False

    openaire_id = record.get("id")
    candidates = build_openaire_fields(record)
    filled, offered = apply_enrichment(work, candidates, "openaire")

    provenance = work.provenance if isinstance(work.provenance, dict) else {}
    provenance["openaire_match"] = {
        "status": "matched",
        "openaire_id": openaire_id,
        "num_found": 1,
    }
    work.provenance = provenance
    append_event(
        work,
        "openaire_enrich",
        openaire_id=openaire_id,
        doi=doi or None,
        source_url=f"{OPENAIRE_API_URL}?pid={doi}",
        fields_filled=filled or None,
        fields_offered_not_applied=offered or None,
    )

    if save:
        work.save(update_fields=[*filled, "provenance", "lastUpdate"])
    return bool(filled)


def enrich_event_from_openaire(event_id, throttle=None):
    """Async sweep: enrich a harvest event's works that are missing target fields.

    Enqueued by ``complete_harvest`` after every successful harvest (gated by
    ``OPTIMAP_OPENAIRE_ENRICH_ON_HARVEST``). Throttles between requests to respect
    OpenAIRE's rate limit (60/hour anonymous, 7200/hour with a token). Returns the
    number of works updated.
    """
    try:
        event = HarvestingEvent.objects.get(id=event_id)
    except HarvestingEvent.DoesNotExist:
        logger.warning("OpenAIRE sweep: harvesting event %s not found", event_id)
        return 0

    if throttle is None:
        throttle = settings.OPTIMAP_OPENAIRE_ENRICH_THROTTLE

    qs = (
        event.works.filter(doi__isnull=False)
        .exclude(doi="")
        .filter(
            Q(abstract__isnull=True)
            | Q(abstract="")
            | Q(keywords__isnull=True)
            | Q(keywords=[])
            | Q(authors__isnull=True)
            | Q(authors=[])
        )
        .order_by("id")
    )
    total = qs.count()
    logger.info("OpenAIRE sweep for event %s: %d candidate work(s)", event_id, total)
    if not total:
        return 0

    session = _openaire_session()
    updated = 0
    try:
        for i, work in enumerate(qs.iterator(chunk_size=50)):
            try:
                if enrich_work_from_openaire(work, session=session):
                    updated += 1
            except Exception as exc:
                logger.warning("OpenAIRE enrich failed for work %s (%s): %s", work.id, work.doi, exc)
            if i + 1 < total and throttle:
                time.sleep(throttle)
    finally:
        session.close()

    logger.info("OpenAIRE sweep for event %s done: %d/%d work(s) updated", event_id, updated, total)
    return updated
