# SPDX-FileCopyrightText: 2026 OPTIMETA and KOMET projects <https://projects.tib.eu/komet>
# SPDX-License-Identifier: GPL-3.0-or-later

"""OAI-PMH harvester (also used for OJS and Janeway sources, which expose
the same protocol).

Public surface:
- ``parse_oai_xml_and_save_works`` — parse a ListRecords payload into Works.
- ``harvest_oai_endpoint`` — Django-Q task: fetch + parse + persist + notify.
"""

import logging
import re
from urllib.parse import urlsplit
from xml.dom import minidom

import requests
from bs4 import BeautifulSoup
from django.contrib.gis.geos import GeometryCollection
from django.db import transaction
from django.utils import timezone

from works.models import HarvestingEvent, Source

from .common import (
    HarvestStats,
    HarvestWarningCollector,
    _save_or_update_work,
    complete_harvest,
    ensure_collection_for_source,
    fail_harvest,
    get_or_create_admin_command_user,
    parse_publication_date,
    render_harvest_email,
    resolve_user,
    send_harvest_email,
)
from .metadata_html import extract_geometry_from_html, extract_timeperiod_from_html
from .openalex import build_openalex_fields
from .sessions import (
    OAI_HTTP_TIMEOUT,
    OAI_RETRY_TOTAL,
    _looks_like_oai_xml,
    _oai_session,
    _short_body,
)

logger = logging.getLogger(__name__)
DOI_REGEX = re.compile(r'10\.\d{4,9}/[-._;()/:A-Z0-9]+', re.IGNORECASE)


def parse_oai_xml_and_save_works(content, event: HarvestingEvent, max_records=None, warning_collector=None, update_existing=False, stats=None):
    source = event.source
    logger.info("Starting OAI-PMH parsing for source: %s", source.name)
    parsed = urlsplit(source.url_field)
    if stats is None:
        stats = HarvestStats()

    if content and len(content.strip()) > 0:
        logger.debug("Parsing XML content from response")
        try:
            dom = minidom.parseString(content)
            records = dom.documentElement.getElementsByTagName("record")
            logger.info("Found %d records in XML response", len(records))
        except Exception as e:
            logger.error("Failed to parse XML content: %s", str(e))
            logger.warning("No articles found in OAI-PMH response!")
            return
    else:
        logger.warning("Empty or no content provided - cannot harvest")
        return

    if not records:
        logger.warning("No articles found in OAI-PMH response!")
        return

    if max_records and hasattr(records, '__len__'):
        records = records[:max_records]
        logger.info("Limited to first %d records", max_records)
    elif max_records:
        records = list(records)[:max_records]
        logger.info("Limited to first %d records", max_records)

    processed_count = 0

    total_records = len(records) if hasattr(records, '__len__') else None
    log_interval = max(1, total_records // 10) if total_records else 10

    for rec in records:
        try:
            processed_count += 1
            if processed_count % log_interval == 0:
                logger.debug("Processing record %d of %d", processed_count, total_records if total_records else '?')

            if hasattr(rec, "metadata"):
                identifiers = rec.metadata.get("identifier", []) + rec.metadata.get("relation", [])
                get_field = lambda k: rec.metadata.get(k, [""])[0]
            else:
                id_nodes = rec.getElementsByTagName("dc:identifier")
                identifiers = [
                    n.firstChild.nodeValue.strip()
                    for n in id_nodes
                    if n.firstChild and n.firstChild.nodeValue
                ]
                def get_field(tag):
                    nodes = rec.getElementsByTagName(tag)
                    return nodes[0].firstChild.nodeValue.strip() if nodes and nodes[0].firstChild else None

            http_urls = [u for u in identifiers if u and u.lower().startswith("http")]
            view_urls = [u for u in http_urls if "/view/" in u]
            identifier_value = (view_urls or http_urls or [None])[0]

            title_value    = get_field("title")       or get_field("dc:title")
            abstract_text  = get_field("description") or get_field("dc:description")
            publisher_value  = get_field("publisher")   or get_field("dc:publisher")
            raw_date_value = get_field("date")        or get_field("dc:date")
            date_value     = parse_publication_date(raw_date_value)

            logger.debug("Processing work: %s", title_value[:50] if title_value else 'No title')

            doi_text = None
            issn_text = None
            for u in identifiers:
                if u and (m := DOI_REGEX.search(u)):
                    doi_text = m.group(0)
                    break

            issn_candidates = []
            issn_candidates.extend(identifiers)
            issn_candidates.append(get_field("source") or get_field("dc:source"))
            issn_candidates.append(get_field("relation") or get_field("dc:relation"))

            for candidate in issn_candidates:
                if candidate and len(candidate.replace('-', '')) == 8 and candidate.replace('-', '').isdigit():
                    issn_text = candidate
                    break

            # Per-source dedup happens later in _save_or_update_work; cheap pre-check
            # for invalid URLs avoids building unused metadata.
            if not identifier_value or not identifier_value.startswith("http"):
                logger.debug("Skipping invalid URL: %s", identifier_value)
                continue

            src_obj = source

            if issn_text:
                try:
                    src_obj = Source.objects.get(issn_l=issn_text)
                    logger.debug("Matched source by ISSN %s: %s", issn_text, src_obj.name)
                except Source.DoesNotExist:
                    if publisher_value:
                        src_obj, created = Source.objects.get_or_create(
                            issn_l=issn_text,
                            defaults={'name': publisher_value}
                        )
                        if created:
                            logger.debug("Created new source with ISSN %s: %s", issn_text, publisher_value)
                    else:
                        src_obj, created = Source.objects.get_or_create(
                            issn_l=issn_text,
                            defaults={'name': f'Unknown Source (ISSN: {issn_text})'}
                        )
                        if created:
                            logger.debug("Created new source with ISSN %s", issn_text)
            elif publisher_value:
                src_obj, created = Source.objects.get_or_create(name=publisher_value)
                if created:
                    logger.debug("Created new source by name: %s", publisher_value)

            geom_obj = GeometryCollection()
            period_start, period_end = [], []
            geometry_source_label = None
            try:
                logger.debug("Fetching HTML content for geometry extraction: %s", identifier_value)
                resp = requests.get(identifier_value, timeout=10)
                resp.raise_for_status()
                soup = BeautifulSoup(resp.content, "html.parser")
                extracted, geometry_source_label = extract_geometry_from_html(
                    soup, base_url=identifier_value,
                )
                if extracted is not None:
                    geom_obj = extracted
                    logger.debug(
                        "Extracted geometry from HTML for %s via %s",
                        identifier_value, geometry_source_label,
                    )
                ts, te = extract_timeperiod_from_html(soup)
                if ts: period_start = ts
                if te: period_end   = te
            except Exception as fetch_err:
                logger.debug("Error fetching HTML for %s: %s", identifier_value, fetch_err)

            author_field = get_field("creator") or get_field("dc:creator")
            authors_list = []
            if author_field:
                authors_list = [a.strip() for a in author_field.replace(';', ',').split(',') if a.strip()]

            subject_field = get_field("subject") or get_field("dc:subject")
            keywords_list = []
            if subject_field:
                keywords_list = [k.strip() for k in subject_field.replace(';', ',').split(',') if k.strip()]

            existing_metadata = {}
            if authors_list:
                existing_metadata['authors'] = authors_list
            if keywords_list:
                existing_metadata['keywords'] = keywords_list

            openalex_fields, metadata_provenance = build_openalex_fields(
                title=title_value,
                doi=doi_text,
                author=author_field,
                existing_metadata=existing_metadata
            )

            if geometry_source_label:
                metadata_provenance['geometry'] = geometry_source_label

            try:
                with transaction.atomic():
                    admin_user = get_or_create_admin_command_user()

                    provenance = {
                        "harvest": {
                            "harvester": "harvest_oai_endpoint",
                            "source_url": source.url_field,
                            "source_type": source.source_type,
                            "source_name": source.name,
                            "harvested_at": timezone.now().isoformat(),
                            "harvesting_event_id": event.id,
                        },
                        "metadata_sources": dict(metadata_provenance or {}),
                    }

                    if 'type' not in openalex_fields:
                        openalex_fields['type'] = src_obj.default_work_type if src_obj else "article"

                    work_kwargs = dict(
                        title                = title_value,
                        abstract             = abstract_text,
                        publicationDate      = date_value,
                        url                  = identifier_value,
                        doi                  = doi_text,
                        source               = src_obj,
                        status               = "h",
                        geometry             = geom_obj,
                        timeperiod_startdate = period_start,
                        timeperiod_enddate   = period_end,
                        job                  = event,
                        provenance           = provenance,
                        created_by           = admin_user,
                        **openalex_fields,
                    )
                    work, action = _save_or_update_work(
                        work_kwargs, source, event, update_existing=update_existing,
                    )
                    stats.record(action)
                    if action in ('created', 'updated'):
                        # Propagate the harvest's source collection to the work
                        # (no-op when the source has no collection set). The
                        # *event's* source wins over the per-record ISSN-matched
                        # src_obj — the operator's intent for this harvest takes
                        # precedence over per-record source switching.
                        if source and source.collection_id:
                            work.collections.add(source.collection_id)
                    if action == 'created':
                        logger.info("Saved work id=%s: %s", work.id, title_value[:80] if title_value else 'No title')
                    elif action == 'updated':
                        logger.info("Updated work id=%s: %s", work.id, title_value[:80] if title_value else 'No title')
            except Exception as save_err:
                logger.error("Failed to save work '%s': %s", title_value[:80] if title_value else 'No title', save_err)
                continue

        except Exception as e:
            logger.error("Error parsing record %d: %s", processed_count, e)
            continue

    logger.info(
        "OAI-PMH parsing completed for source %s: processed %d records, created %d, updated %d, skipped %d",
        source.name, processed_count, stats.created, stats.updated,
        stats.skipped_same_source + stats.skipped_cross_source,
    )


def harvest_oai_endpoint(source_id, user=None, max_records=None, update_existing=False):
    user = resolve_user(user)
    source = Source.objects.get(id=source_id)
    # Issue #192: the generic OAI-PMH harvester creates a Collection for each
    # endpoint on first run if the admin hasn't pre-assigned one. The new
    # Collection starts unpublished so the admin can review the auto-derived
    # name/description before flipping it on. No-op when source.collection is
    # already set (e.g. via harvest_sources --insert-sources).
    ensure_collection_for_source(source)
    event  = HarvestingEvent.objects.create(source=source, status="in_progress")

    new_count = None
    spatial_count = None
    temporal_count = None

    warning_collector = HarvestWarningCollector()
    warning_collector.setLevel(logging.INFO)
    logger.addHandler(warning_collector)

    try:
        if '?' not in source.url_field:
            oai_url = f"{source.url_field}?verb=ListRecords&metadataPrefix=oai_dc"
        else:
            oai_url = source.url_field

        logger.info("Fetching from OAI-PMH URL: %s", oai_url)
        session = _oai_session()
        try:
            response = session.get(oai_url, timeout=OAI_HTTP_TIMEOUT)
        except requests.exceptions.Timeout as e:
            raise RuntimeError(
                f"OAI-PMH endpoint timed out after {OAI_HTTP_TIMEOUT}s "
                f"(after {OAI_RETRY_TOTAL} retries): {oai_url}"
            ) from e
        except requests.exceptions.ConnectionError as e:
            raise RuntimeError(
                f"OAI-PMH endpoint unreachable (after {OAI_RETRY_TOTAL} retries): "
                f"{oai_url}: {e}"
            ) from e

        if not response.ok:
            content_type = response.headers.get("Content-Type", "?")
            raise RuntimeError(
                f"OAI-PMH endpoint returned HTTP {response.status_code} "
                f"({content_type}) for {oai_url}. "
                f"This usually means the URL is outdated or the upstream is "
                f"down. Body preview: {_short_body(response)}"
            )

        if not _looks_like_oai_xml(response.content):
            content_type = response.headers.get("Content-Type", "?")
            raise RuntimeError(
                f"OAI-PMH endpoint returned non-XML content "
                f"(HTTP {response.status_code}, Content-Type: {content_type}) "
                f"for {oai_url}. Body preview: {_short_body(response)}"
            )

        stats = HarvestStats()
        parse_oai_xml_and_save_works(
            response.content, event,
            max_records=max_records,
            warning_collector=warning_collector,
            update_existing=update_existing,
            stats=stats,
        )

        spatial_count, temporal_count = complete_harvest(event, stats, warning_collector)
        new_count = stats.created
        updated_count = stats.updated

        collection_label = source.collection.name if source.collection else source.name
        subject, body = render_harvest_email('email/harvest_success.en.txt', {
            'subject_prefix': '',
            'source_label': collection_label,
            'detail_header': 'Harvesting job details:',
            'source_name': source.name,
            'source_url': source.url_field,
            'url_label': 'Journal',
            'collection_label': collection_label,
            'records_added_label': 'Number of added articles',
            'records_added': new_count,
            'records_updated_label': 'Number of updated articles',
            'records_updated': updated_count,
            'spatial_label': 'Number of articles with spatial metadata',
            'spatial_count': spatial_count,
            'temporal_label': 'Number of articles with temporal metadata',
            'temporal_count': temporal_count,
            'event_started': event.started_at.strftime('%Y-%m-%d %H:%M:%S'),
            'event_completed': event.completed_at.strftime('%Y-%m-%d %H:%M:%S'),
            'warning_summary': warning_collector.get_summary(),
            'resolved_prefix': None,
            'container_title_filters': None,
            'openalex_source_id': None,
            'records_seen': None,
            'records_processed': None,
        })
        send_harvest_email(user, subject, body)

    except Exception as e:
        logger.error("Harvesting failed for source %s: %s", source.url_field, str(e))
        fail_harvest(event, e, warning_collector)
        collection_label = source.collection.name if source.collection else source.name
        subject, body = render_harvest_email('email/harvest_failure.en.txt', {
            'subject_prefix': '',
            'source_label': collection_label,
            'source_type_label': 'OAI-PMH',
            'source_name': source.name,
            'source_url': source.url_field,
            'collection_label': collection_label,
            'resolved_prefix': None,
            'event_started': event.started_at.strftime('%Y-%m-%d %H:%M:%S'),
            'event_failed': event.completed_at.strftime('%Y-%m-%d %H:%M:%S'),
            'error': str(e),
            'warning_summary': warning_collector.get_summary() if warning_collector.has_issues() else '',
        })
        send_harvest_email(user, subject, body)
    finally:
        logger.removeHandler(warning_collector)

    return new_count, spatial_count, temporal_count
