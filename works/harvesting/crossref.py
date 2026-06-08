# SPDX-FileCopyrightText: 2026 OPTIMETA and KOMET projects <https://projects.tib.eu/komet>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Crossref-prefix harvester (fallback for Copernicus, see issue tracker).

The OAI-PMH endpoint at https://oai-pmh.copernicus.org/oai.php went 404
sometime between the 2025-12-15 Wayback snapshot and 2026-04-29. While the
upstream is dark, we can reach the same metadata through Crossref using
Copernicus's DOI prefix 10.5194 (publisher = "Copernicus GmbH"). The
trade-off: Crossref supplies <jats:p> abstracts that are usually OK, but
the publisher-side article landing pages serve the canonical, fully-
punctuated abstract. This task fetches abstracts directly from the
journal subdomain by default, falling back to the Crossref payload only
when the landing-page fetch fails.
"""

import logging
from datetime import datetime

import requests
from bs4 import BeautifulSoup
from django.utils import timezone

from works.models import HarvestingEvent, Source

from works.utils.provenance import append_event

from .bok_pdf import agile_giss_doi_to_pdf_url, extract_bok_from_agile_pdf
from .common import (
    HarvestStats,
    HarvestWarningCollector,
    _save_or_update_work,
    complete_harvest,
    fail_harvest,
    render_harvest_email,
    resolve_user,
    send_harvest_email,
)
from .sessions import (
    CROSSREF_API_URL,
    CROSSREF_HTTP_TIMEOUT,
    CROSSREF_PAGE_ROWS,
    _crossref_session,
)

logger = logging.getLogger(__name__)


def _strip_jats(jats_html):
    """Strip JATS XML tags from a Crossref abstract.

    Crossref returns abstracts wrapped in <jats:p>, with optional
    <jats:italic>, <jats:sub>, etc. inline. We just want the plain text.
    """
    if not jats_html:
        return None
    soup = BeautifulSoup(jats_html, "html.parser")
    return soup.get_text(separator=" ", strip=True) or None


def _build_crossref_filter(prefix, source_titles=None, since=None):
    """Assemble a Crossref ``filter=...`` parameter value."""
    parts = [f"prefix:{prefix}"]
    if source_titles:
        # Crossref lets the same filter key repeat — each title becomes its
        # own clause, and Crossref ORs same-key filters. So a multi-title
        # request widens the result set rather than narrowing it.
        for title in source_titles:
            parts.append(f"container-title:{title}")
    if since:
        parts.append(f"from-update-date:{since}")
    return ",".join(parts)


def fetch_copernicus_abstract(landing_url, session=None):
    """Fetch the canonical abstract from a Copernicus journal landing page.

    Returns the plain-text abstract or ``None`` on any failure (network,
    parse, missing selector). Failure is logged at INFO so the caller can
    fall back to the Crossref-supplied abstract without aborting the harvest.
    """
    if not landing_url:
        return None
    s = session or _crossref_session()
    try:
        resp = s.get(landing_url, timeout=CROSSREF_HTTP_TIMEOUT, allow_redirects=True)
    except requests.exceptions.RequestException as e:
        logger.info("Abstract fetch failed for %s: %s", landing_url, e)
        return None
    if not resp.ok:
        logger.info(
            "Abstract fetch returned HTTP %s for %s",
            resp.status_code, landing_url,
        )
        return None
    soup = BeautifulSoup(resp.content, "html.parser")
    div = soup.select_one("div.abstract, div#abstract")
    if div:
        text = div.get_text(separator=" ", strip=True)
        if text.lower().startswith("abstract"):
            text = text[len("abstract"):].lstrip(" .:")
        return text or None
    meta = soup.select_one('meta[name="citation_abstract"]')
    if meta and meta.get("content"):
        return BeautifulSoup(meta["content"], "html.parser").get_text(
            separator=" ", strip=True
        ) or None
    return None


def _authors_from_crossref(authors):
    """Crossref ``author`` → list of ``"Given Family"`` strings.

    Crossref entries occasionally only have ``family`` (corporate authors) or
    only ``given`` — keep whatever is there rather than dropping the row.
    """
    if not authors:
        return []
    out = []
    for a in authors:
        if not isinstance(a, dict):
            continue
        given = (a.get("given") or "").strip()
        family = (a.get("family") or "").strip()
        name = a.get("name") or " ".join(p for p in (given, family) if p).strip()
        if name:
            out.append(name)
    return out


def _split_crossref_page(page):
    """``"12-25"`` → ``("12", "25")``; single locator → ``(value, None)``."""
    if not page:
        return None, None
    text = page.strip()
    if not text:
        return None, None
    if "-" in text:
        first, _, last = text.partition("-")
        first = first.strip() or None
        last = last.strip() or None
        return first, last
    return text, None


def _crossref_item_to_work_kwargs(
    item, source, event, fetch_abstract_from_publisher, abstract_session
):
    """Convert a Crossref `works` JSON item to ``Work.objects.create`` kwargs.

    Returns ``None`` if the item lacks the minimum identifier (DOI). Abstract
    resolution prefers the publisher landing page (when ``fetch_abstract_
    from_publisher`` is on) and falls back to the Crossref-supplied JATS.
    """
    doi = item.get("DOI")
    if not doi:
        return None

    url = item.get("URL") or f"https://doi.org/{doi}"
    title_list = item.get("title") or []
    title = title_list[0] if title_list else doi

    published = (
        item.get("published-print")
        or item.get("published-online")
        or item.get("published")
        or item.get("issued")
        or {}
    )
    pub_date = None
    parts = (published.get("date-parts") or [[]])[0]
    if parts:
        try:
            year = int(parts[0])
            month = int(parts[1]) if len(parts) > 1 else 1
            day = int(parts[2]) if len(parts) > 2 else 1
            pub_date = datetime(year, month, day).date()
        except (TypeError, ValueError):
            pub_date = None

    abstract = None
    if fetch_abstract_from_publisher:
        abstract = fetch_copernicus_abstract(url, session=abstract_session)
    if not abstract:
        abstract = _strip_jats(item.get("abstract"))

    authors = _authors_from_crossref(item.get("author"))
    volume = (item.get("volume") or None) or None
    issue = (item.get("issue") or None) or None
    first_page, last_page = _split_crossref_page(item.get("page"))

    metadata_sources = {"crossref": "doi"}
    if authors:
        metadata_sources["authors"] = "crossref"
    if volume or issue or first_page or last_page:
        metadata_sources["biblio"] = "crossref"

    return {
        "title": title,
        "abstract": abstract,
        "doi": doi,
        "url": url,
        "publicationDate": pub_date,
        "source": source,
        "job": event,
        "authors": authors or None,
        "volume": volume,
        "issue": issue,
        "first_page": first_page,
        "last_page": last_page,
        "type": (source.default_work_type if source else None) or "article",
        "provenance": {
            "harvest": {
                "harvester": "harvest_crossref_prefix",
                "source_url": "https://api.crossref.org/works",
                "source_type": source.source_type if source else "crossref-prefix",
                "source_name": source.name if source else None,
                "harvested_at": timezone.now().isoformat(),
                "harvesting_event_id": event.id if event else None,
                "doi": doi,
            },
            "metadata_sources": metadata_sources,
        },
        "status": "h",
    }


def _try_bok_pdf_extraction(work, doi: str, session) -> None:
    """Download the AGILE GISS PDF for *work* and save extracted BoK codes.

    No-op for non-AGILE DOIs or when bok_concepts are already set.
    All errors are swallowed so harvest never fails due to PDF issues.
    """
    if not agile_giss_doi_to_pdf_url(doi):
        return
    if work.bok_concepts:
        return
    codes = extract_bok_from_agile_pdf(doi, session=session)
    if not codes:
        return
    pdf_url = agile_giss_doi_to_pdf_url(doi)
    work.bok_concepts = codes
    prov = work.provenance if isinstance(work.provenance, dict) else {}
    prov.setdefault("metadata_sources", {})["bok_concepts"] = "pdf_extraction"
    work.provenance = prov
    append_event(
        work,
        "bok_pdf_extract",
        source="pdf",
        pdf_url=pdf_url,
        codes_found=codes,
    )
    work.save(update_fields=["bok_concepts", "provenance"])
    logger.info("BoK PDF extraction: set %s on work %s", codes, work.id)


def parse_crossref_response_and_save_works(
    source, event, prefix, source_titles=None,
    fetch_abstract_from_publisher=True, max_records=None,
    warning_collector=None, update_existing=False, stats=None,
    sort=None, order=None,
):
    """Page through Crossref's ``works`` API and persist matched works.

    Uses cursor-based pagination (``cursor=*`` then echo back), 100 rows per
    page. Stops after ``max_records`` items have been processed (useful for
    smoke tests). Items already present in the DB by DOI are skipped to
    keep the harvest idempotent on re-run.

    ``sort`` / ``order`` map to Crossref's ``sort=`` / ``order=`` query
    parameters (e.g. ``sort='published', order='desc'``). Default is
    Crossref's default (relevance/score), which is fine for a steady-state
    crawl but useless for "most recent first" comparison runs.
    """
    session = _crossref_session()
    cursor = "*"
    saved = 0
    seen = 0
    if stats is None:
        stats = HarvestStats()

    filter_value = _build_crossref_filter(prefix, source_titles=source_titles)

    while True:
        params = {
            "filter": filter_value,
            "rows": str(CROSSREF_PAGE_ROWS),
            "cursor": cursor,
            "select": (
                "DOI,title,abstract,published-print,published-online,"
                "published,issued,URL,container-title,publisher,"
                "author,volume,issue,page"
            ),
        }
        if sort:
            params["sort"] = sort
        if order:
            params["order"] = order
        try:
            resp = session.get(
                CROSSREF_API_URL, params=params, timeout=CROSSREF_HTTP_TIMEOUT
            )
        except requests.exceptions.RequestException as e:
            raise RuntimeError(f"Crossref request failed: {e}") from e
        if not resp.ok:
            raise RuntimeError(
                f"Crossref returned HTTP {resp.status_code} for filter "
                f"{filter_value!r}: {resp.text[:300]}"
            )

        data = resp.json().get("message", {})
        items = data.get("items", [])
        if not items:
            break

        for item in items:
            seen += 1
            kwargs = _crossref_item_to_work_kwargs(
                item, source, event,
                fetch_abstract_from_publisher,
                session,
            )
            if not kwargs:
                continue
            try:
                work, action = _save_or_update_work(
                    kwargs, source, event, update_existing=update_existing,
                )
                stats.record(action)
                if action in ('created', 'updated') and source and source.collection_id:
                    work.collections.add(source.collection_id)
                if action == 'created':
                    saved += 1
                    _try_bok_pdf_extraction(work, kwargs.get("doi", ""), session)
            except Exception as e:
                logger.warning(
                    "Failed to persist Crossref work %s: %s", kwargs.get("doi"), e,
                )
            if max_records and seen >= max_records:
                return saved, seen

        next_cursor = data.get("next-cursor")
        if not next_cursor or next_cursor == cursor:
            break
        cursor = next_cursor

    return saved, seen


def harvest_crossref_prefix(
    source_id, user=None, max_records=None,
    source_titles=None, prefix=None,
    fetch_abstract_from_publisher=True,
    update_existing=False,
    sort=None, order=None,
):
    """Harvest publications from Crossref by DOI prefix.

    Used as a fallback for Copernicus while their OAI-PMH endpoint is down.
    """
    user = resolve_user(user)
    source = Source.objects.get(id=source_id)
    event  = HarvestingEvent.objects.create(source=source, status="in_progress")

    warning_collector = HarvestWarningCollector()
    warning_collector.setLevel(logging.INFO)
    logger.addHandler(warning_collector)

    resolved_prefix = (
        prefix
        or getattr(source, "crossref_prefix", None)
        or "10.5194"
    )

    try:
        logger.info(
            "Starting Crossref harvest: prefix=%s titles=%s max_records=%s",
            resolved_prefix, source_titles, max_records,
        )
        stats = HarvestStats()
        saved, seen = parse_crossref_response_and_save_works(
            source, event,
            prefix=resolved_prefix,
            source_titles=source_titles,
            fetch_abstract_from_publisher=fetch_abstract_from_publisher,
            max_records=max_records,
            warning_collector=warning_collector,
            update_existing=update_existing,
            stats=stats,
            sort=sort, order=order,
        )

        spatial_count, temporal_count = complete_harvest(event, stats, warning_collector)

        subject, body = render_harvest_email('email/harvest_success.en.txt', {
            'subject_prefix': 'Crossref ',
            'source_label': source.name,
            'detail_header': 'Crossref harvest details:',
            'source_name': source.name,
            'source_url': None,
            'url_label': None,
            'collection_label': None,
            'records_added_label': 'New works saved',
            'records_added': stats.created,
            'records_updated_label': 'Updated works',
            'records_updated': stats.updated,
            'spatial_label': 'Articles with spatial metadata',
            'spatial_count': spatial_count,
            'temporal_label': 'Articles with temporal metadata',
            'temporal_count': temporal_count,
            'event_started': f'{event.started_at:%Y-%m-%d %H:%M:%S}',
            'event_completed': f'{event.completed_at:%Y-%m-%d %H:%M:%S}',
            'warning_summary': warning_collector.get_summary(),
            'resolved_prefix': resolved_prefix,
            'container_title_filters': ', '.join(source_titles) if source_titles else '<all>',
            'openalex_source_id': None,
            'records_seen': seen,
            'records_processed': None,
        })
        send_harvest_email(user, subject, body)

    except Exception as e:
        logger.error(
            "Crossref harvesting failed for source %s: %s",
            source.url_field, str(e),
        )
        fail_harvest(event, e, warning_collector)
        subject, body = render_harvest_email('email/harvest_failure.en.txt', {
            'subject_prefix': 'Crossref ',
            'source_label': source.name,
            'source_type_label': 'Crossref',
            'source_name': source.name,
            'source_url': None,
            'collection_label': None,
            'resolved_prefix': resolved_prefix,
            'event_started': None,
            'event_failed': None,
            'error': str(e),
            'warning_summary': '',
        })
        send_harvest_email(user, subject, body, fail_silently=True)
        raise
    finally:
        logger.removeHandler(warning_collector)
