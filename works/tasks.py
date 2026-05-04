# SPDX-FileCopyrightText: 2022 OPTIMETA and KOMET projects <https://projects.tib.eu/komet>
# SPDX-License-Identifier: GPL-3.0-or-later

import logging
import os
import gzip
import glob
import re
import tempfile
import glob
import json
import time
import tempfile 
import calendar
import subprocess
from pathlib import Path
from datetime import datetime, date, timedelta, timezone as dt_timezone
from urllib.parse import urlsplit, urlunsplit, quote, urljoin
import xml.dom.minidom

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from pathlib import Path
from bs4 import BeautifulSoup
from xml.dom import minidom

from urllib.parse import quote
from django.conf import settings
from django.core.serializers import serialize
from django.core.mail import send_mail, EmailMessage
from django.utils import timezone
from django.db import transaction
from django.contrib.gis.geos import GEOSGeometry, GeometryCollection, Polygon
from django_q.tasks import schedule
from django_q.models import Schedule
from django.contrib.auth import get_user_model
from works.models import Work, HarvestingEvent, Source, EmailLog, Subscription
from django.urls import reverse
User = get_user_model()
from oaipmh_scythe import Scythe
from urllib.parse import urlsplit, urlunsplit
from django.contrib.gis.geos import GeometryCollection
from bs4 import BeautifulSoup
import requests
from .models import EmailLog, Subscription
from django.urls import reverse
from geopy.geocoders import Nominatim
from django.contrib.gis.geos import Point
from .openalex_matcher import get_openalex_matcher

logger = logging.getLogger(__name__)
BASE_URL = settings.BASE_URL
DOI_REGEX = re.compile(r'10\.\d{4,9}/[-._;()/:A-Z0-9]+', re.IGNORECASE)
CACHE_DIR = Path(tempfile.gettempdir()) / 'optimap_cache'


class HarvestWarningCollector(logging.Handler):
    """
    Custom logging handler to collect warning and error messages during harvesting.

    This handler collects messages for email summaries while also ensuring they are
    logged to the standard output/error through the normal logging chain.

    Categorizes messages with emoji severity indicators:
    - 🔴 ERROR: Critical errors that prevented processing
    - 🟡 WARNING: Issues that didn't prevent processing but need attention
    - 🔵 INFO: Important informational messages
    """

    def __init__(self, passthrough=True):
        """
        Initialize the warning collector.

        Args:
            passthrough: If True, allows log records to propagate to other handlers (default: True)
        """
        super().__init__()
        self.warnings = []
        self.errors = []
        self.info = []
        self.passthrough = passthrough

    def emit(self, record):
        """
        Collect log records by severity and allow them to propagate to other handlers.

        This method collects messages for the email summary but does NOT prevent
        them from being logged to stdout/stderr by other handlers.
        """
        # Format the message for our internal collection
        message = self.format(record)

        # Collect by severity
        if record.levelno >= logging.ERROR:
            self.errors.append(f"🔴 ERROR: {message}")
        elif record.levelno >= logging.WARNING:
            self.warnings.append(f"🟡 WARNING: {message}")
        elif record.levelno >= logging.INFO and any(keyword in message.lower() for keyword in ['no openalex match', 'openalex matching failed', 'skipping']):
            self.info.append(f"🔵 INFO: {message}")

        # Note: We do NOT call super().emit() because that would try to write somewhere.
        # The record will naturally propagate to other handlers in the logger's handler list.
        # By not raising an exception or calling super().emit(), we allow the logging
        # framework to continue processing this record with other handlers.

    def get_summary(self):
        """Return a formatted summary of all collected messages."""
        summary_parts = []

        if self.errors:
            summary_parts.append(f"\n{'='*70}\n🔴 ERRORS ({len(self.errors)})\n{'='*70}")
            summary_parts.extend(self.errors)

        if self.warnings:
            summary_parts.append(f"\n{'='*70}\n🟡 WARNINGS ({len(self.warnings)})\n{'='*70}")
            summary_parts.extend(self.warnings)

        if self.info:
            summary_parts.append(f"\n{'='*70}\n🔵 NOTABLE INFORMATION ({len(self.info)})\n{'='*70}")
            summary_parts.extend(self.info)

        if not (self.errors or self.warnings or self.info):
            return "\n✅ No warnings or errors during harvesting!"

        return "\n".join(summary_parts)

    def has_issues(self):
        """Check if any warnings or errors were collected."""
        return bool(self.errors or self.warnings or self.info)


def build_openalex_fields(title, doi=None, author=None, existing_metadata=None):
    """
    Match a work against OpenAlex and return the appropriate fields dictionary.

    This function prioritizes existing metadata from the original source and only fills
    in missing information from OpenAlex.

    Args:
        title: Work title (required)
        doi: Work DOI (optional)
        author: Work author (optional)
        existing_metadata: Dict of metadata already extracted from original source (optional)

    Returns:
        tuple: (openalex_fields dict, metadata_provenance dict)
              openalex_fields: Dictionary containing fields to be unpacked into Work.objects.create()
              metadata_provenance: Dictionary tracking the source of each metadata field
    """
    if existing_metadata is None:
        existing_metadata = {}

    openalex_fields = {}
    metadata_provenance = {}

    try:
        matcher = get_openalex_matcher()
        openalex_data, partial_matches = matcher.match_publication(
            title=title,
            doi=doi,
            author=author
        )

        if openalex_data:
            # Perfect match found
            logger.debug("OpenAlex match found for: %s", title[:50] if title else 'No title')

            # Merge fields, prioritizing existing metadata
            # Authors: use existing if available, otherwise OpenAlex
            if existing_metadata.get('authors'):
                openalex_fields['authors'] = existing_metadata['authors']
                metadata_provenance['authors'] = 'original_source'
            elif openalex_data.get('authors'):
                openalex_fields['authors'] = openalex_data['authors']
                metadata_provenance['authors'] = 'openalex'

            # Keywords: use existing if available, otherwise OpenAlex
            if existing_metadata.get('keywords'):
                openalex_fields['keywords'] = existing_metadata['keywords']
                metadata_provenance['keywords'] = 'original_source'
            elif openalex_data.get('keywords'):
                openalex_fields['keywords'] = openalex_data['keywords']
                metadata_provenance['keywords'] = 'openalex'

            # Topics: only from OpenAlex (original sources typically don't have topic classification)
            if openalex_data.get('topics'):
                openalex_fields['topics'] = openalex_data['topics']
                metadata_provenance['topics'] = 'openalex'

            # Type: use OpenAlex type if available (overrides source default)
            if openalex_data.get('type'):
                openalex_fields['type'] = openalex_data['type']
                metadata_provenance['type'] = 'openalex'

            # OpenAlex-specific fields (always from OpenAlex)
            openalex_fields['openalex_id'] = openalex_data.get('openalex_id')
            openalex_fields['openalex_fulltext_origin'] = openalex_data.get('openalex_fulltext_origin')
            openalex_fields['openalex_is_retracted'] = openalex_data.get('openalex_is_retracted', False)
            openalex_fields['openalex_ids'] = openalex_data.get('openalex_ids', {})
            openalex_fields['openalex_open_access_status'] = openalex_data.get('openalex_open_access_status')

            metadata_provenance['openalex_metadata'] = 'openalex'

        elif partial_matches:
            # No perfect match, store partial match info
            openalex_fields['openalex_id'] = None
            openalex_fields['openalex_match_info'] = partial_matches
            logger.debug("OpenAlex partial matches found for: %s", title[:50] if title else 'No title')

            # Still use existing metadata if available
            if existing_metadata.get('authors'):
                openalex_fields['authors'] = existing_metadata['authors']
                metadata_provenance['authors'] = 'original_source'
            if existing_metadata.get('keywords'):
                openalex_fields['keywords'] = existing_metadata['keywords']
                metadata_provenance['keywords'] = 'original_source'

        else:
            # No match at all
            openalex_fields['openalex_id'] = None
            if doi:
                # WARNING: OpenAlex should contain all records with DOI
                logger.warning("No OpenAlex match for work with DOI %s: %s", doi, title[:50] if title else 'No title')
            else:
                logger.debug("No OpenAlex match for: %s", title[:50] if title else 'No title')

            # Use existing metadata if available
            if existing_metadata.get('authors'):
                openalex_fields['authors'] = existing_metadata['authors']
                metadata_provenance['authors'] = 'original_source'
            if existing_metadata.get('keywords'):
                openalex_fields['keywords'] = existing_metadata['keywords']
                metadata_provenance['keywords'] = 'original_source'

    except Exception as openalex_err:
        logger.warning("OpenAlex matching failed for '%s': %s", title[:50] if title else 'No title', openalex_err)
        openalex_fields['openalex_id'] = None

        # Use existing metadata if available
        if existing_metadata.get('authors'):
            openalex_fields['authors'] = existing_metadata['authors']
            metadata_provenance['authors'] = 'original_source'
        if existing_metadata.get('keywords'):
            openalex_fields['keywords'] = existing_metadata['keywords']
            metadata_provenance['keywords'] = 'original_source'

    return openalex_fields, metadata_provenance


def get_or_create_admin_command_user():
    """
    Get or create a dedicated user for Django admin command operations.
    This user is used as the creator for harvested publications.

    Returns:
        User: The Django Admin Command user instance
    """
    username = 'django_admin_command'
    email = 'django_admin_command@system.local'

    user, created = User.objects.get_or_create(
        username=username,
        defaults={
            'email': email,
            'is_active': False,  # System user, not for login
            'is_staff': False,
        }
    )

    if created:
        logger.info("Created system user: %s", username)

    return user


def _get_article_link(work):
    """Prefer our site permalink if DOI exists, else fallback to original URL."""
    if getattr(work, "doi", None):
        base = settings.BASE_URL.rstrip("/")
        return f"{base}/work/{work.doi}"
    return work.url
    

def parse_publication_date(date_string):
    if not date_string:
        return None

    date_string = date_string.strip()

    # Already in correct format
    if re.match(r'^\d{4}-\d{2}-\d{2}$', date_string):
        return date_string

    # YYYY-MM format - add day
    if re.match(r'^\d{4}-\d{2}$', date_string):
        return f"{date_string}-01"

    # YYYY format - add month and day
    if re.match(r'^\d{4}$', date_string):
        return f"{date_string}-01-01"

    # Try to extract year from other formats
    year_match = re.search(r'\b(\d{4})\b', date_string)
    if year_match:
        return f"{year_match.group(1)}-01-01"

    logger.warning("Could not parse date format: %s", date_string)
    return None


def generate_data_dump_filename(extension: str) -> str:
    ts = datetime.now(dt_timezone.utc).strftime("%Y%m%dT%H%M%S")
    return f"optimap_data_dump_{ts}.{extension}"


def cleanup_old_data_dumps(directory: Path, keep: int):
    """
    Deletes all files matching optimap_data_dump_* beyond the newest `keep` ones.
    """
    pattern = str(directory / "optimap_data_dump_*")
    files = sorted(glob.glob(pattern), reverse=True)
    for old in files[keep:]:
        try:
            os.remove(old)
        except OSError:
            logger.warning("Could not delete old dump %s", old)


_GEOJSON_TYPES = {
    "Point", "MultiPoint", "LineString", "MultiLineString",
    "Polygon", "MultiPolygon", "GeometryCollection",
}


def _wrap_in_collection(geom: GEOSGeometry) -> GEOSGeometry:
    # MultiPoint/MultiLineString/MultiPolygon subclass GeometryCollection in
    # Django but are not OGC GeometryCollections — check the OGC type string
    # directly so we always end up with a real GEOMETRYCOLLECTION.
    if geom.geom_type == "GeometryCollection":
        return geom
    return GEOSGeometry(json.dumps({
        "type": "GeometryCollection",
        "geometries": [json.loads(geom.geojson)],
    }))


def _geom_from_geojson_dict(geo: dict) -> GEOSGeometry | None:
    if not isinstance(geo, dict):
        return None
    if geo.get("type") in _GEOJSON_TYPES:
        try:
            return _wrap_in_collection(GEOSGeometry(json.dumps(geo)))
        except Exception:
            return None
    schema_type = geo.get("@type")
    if schema_type == "GeoShape" and isinstance(geo.get("box"), str):
        try:
            south, west, north, east = (float(x) for x in geo["box"].split())
            return _wrap_in_collection(_polygon_from_bbox(west, south, east, north))
        except Exception:
            return None
    if schema_type == "GeoCoordinates":
        try:
            lat = float(geo["latitude"])
            lon = float(geo["longitude"])
            return _wrap_in_collection(GEOSGeometry(f"POINT({lon} {lat})", srid=4326))
        except Exception:
            return None
    return None


def _polygon_from_bbox(west, south, east, north) -> Polygon:
    coords = (
        (west, south), (east, south), (east, north),
        (west, north), (west, south),
    )
    poly = Polygon(coords)
    poly.srid = 4326
    return poly


def _walk_jsonld(node):
    """Yield every dict node inside a JSON-LD document (handles @graph and lists)."""
    if isinstance(node, dict):
        yield node
        for v in node.values():
            yield from _walk_jsonld(v)
    elif isinstance(node, list):
        for item in node:
            yield from _walk_jsonld(item)


def _extract_jsonld_spatial(soup: BeautifulSoup) -> GEOSGeometry | None:
    for tag in soup.find_all("script", attrs={"type": "application/ld+json"}):
        raw = tag.string or tag.get_text() or ""
        if not raw.strip():
            continue
        try:
            doc = json.loads(raw)
        except Exception:
            continue
        for node in _walk_jsonld(doc):
            sc = node.get("spatialCoverage")
            if not sc:
                continue
            candidates = sc if isinstance(sc, list) else [sc]
            for entry in candidates:
                if not isinstance(entry, dict):
                    continue
                geo = entry.get("geo", entry)
                geom = _geom_from_geojson_dict(geo)
                if geom is not None:
                    return geom
    return None


def _extract_geojson_link(soup: BeautifulSoup, base_url: str | None) -> GEOSGeometry | None:
    link = None
    for tag in soup.find_all("link"):
        if tag.get("type") != "application/geo+json":
            continue
        rel = tag.get("rel") or []
        if isinstance(rel, str):
            rel = [rel]
        if "alternate" in rel:
            link = tag
            break
    if link is None or not link.get("href"):
        return None
    href = link["href"]
    if base_url:
        href = urljoin(base_url, href)
    try:
        resp = requests.get(
            href,
            timeout=10,
            headers={"Accept": "application/geo+json, application/json"},
        )
        resp.raise_for_status()
        doc = resp.json()
    except Exception as err:
        logger.debug("geo+json link fetch failed for %s: %s", href, err)
        return None
    geometries = []
    if isinstance(doc, dict):
        if doc.get("type") == "FeatureCollection":
            for feat in doc.get("features") or []:
                g = feat.get("geometry") if isinstance(feat, dict) else None
                if g and g.get("type") in _GEOJSON_TYPES:
                    geometries.append(g)
        elif doc.get("type") == "Feature" and isinstance(doc.get("geometry"), dict):
            geometries.append(doc["geometry"])
        elif doc.get("type") in _GEOJSON_TYPES:
            geometries.append(doc)
    if not geometries:
        return None
    try:
        if len(geometries) == 1:
            return _wrap_in_collection(GEOSGeometry(json.dumps(geometries[0])))
        coll = {"type": "GeometryCollection", "geometries": geometries}
        return GEOSGeometry(json.dumps(coll))
    except Exception as err:
        logger.debug("geo+json parse failed for %s: %s", href, err)
        return None


def _extract_dc_spatial_coverage(soup: BeautifulSoup) -> GEOSGeometry | None:
    for tag in soup.find_all("meta"):
        if tag.get("name") != "DC.SpatialCoverage":
            continue
        try:
            payload = json.loads(tag["content"])
            if payload.get("type") == "FeatureCollection":
                geom_data = payload["features"][0]["geometry"]
            elif payload.get("type") == "Feature":
                geom_data = payload["geometry"]
            else:
                geom_data = payload
            coll = {"type": "GeometryCollection", "geometries": [geom_data]}
            return GEOSGeometry(json.dumps(coll))
        except Exception:
            continue
    return None


def _extract_dc_box(soup: BeautifulSoup) -> GEOSGeometry | None:
    for tag in soup.find_all("meta"):
        if tag.get("name") != "DC.box":
            continue
        try:
            parts = {}
            for chunk in tag.get("content", "").split(";"):
                if "=" not in chunk:
                    continue
                k, v = chunk.split("=", 1)
                parts[k.strip().lower()] = v.strip()
            projection = parts.get("projection", "").upper().replace(":", "")
            if projection and projection not in ("EPSG4326",):
                continue
            west = float(parts["westlimit"])
            south = float(parts["southlimit"])
            east = float(parts["eastlimit"])
            north = float(parts["northlimit"])
            return _wrap_in_collection(_polygon_from_bbox(west, south, east, north))
        except Exception:
            continue
    return None


def extract_geometry_from_html(soup: BeautifulSoup, base_url: str | None = None):
    """Try, in priority order: schema.org JSON-LD spatialCoverage; an
    `application/geo+json` alternate link; DC.SpatialCoverage GeoJSON; DC.box
    bounding box. Returns ``(GEOSGeometry, source_label)`` or ``(None, None)``.
    """
    geom = _extract_jsonld_spatial(soup)
    if geom is not None:
        return geom, "schema.org JSON-LD"
    geom = _extract_geojson_link(soup, base_url)
    if geom is not None:
        return geom, "link rel=alternate geo+json"
    geom = _extract_dc_spatial_coverage(soup)
    if geom is not None:
        return geom, "DC.SpatialCoverage"
    geom = _extract_dc_box(soup)
    if geom is not None:
        return geom, "DC.box"
    return None, None


def _split_iso_interval(value: str):
    """Parse an ISO 8601 interval. Treats '..' or empty as open-ended."""
    if not value:
        return None, None
    value = value.strip()
    if "/" not in value:
        return value, value
    start_raw, end_raw = value.split("/", 1)
    start = start_raw.strip() or None
    end = end_raw.strip() or None
    if start in ("..",):
        start = None
    if end in ("..",):
        end = None
    return start, end


def _extract_jsonld_temporal(soup: BeautifulSoup):
    for tag in soup.find_all("script", attrs={"type": "application/ld+json"}):
        raw = tag.string or tag.get_text() or ""
        if not raw.strip():
            continue
        try:
            doc = json.loads(raw)
        except Exception:
            continue
        for node in _walk_jsonld(doc):
            tc = node.get("temporalCoverage")
            if tc is None:
                continue
            candidate = tc[0] if isinstance(tc, list) and tc else tc
            if not isinstance(candidate, str):
                continue
            return _split_iso_interval(candidate)
    return None


def _extract_dc_temporal(soup: BeautifulSoup):
    for tag in soup.find_all("meta"):
        if tag.get("name") in ("DC.temporal", "DC.PeriodOfTime"):
            return _split_iso_interval(tag.get("content", ""))
    return None


def extract_timeperiod_from_html(soup: BeautifulSoup):
    """Returns ``([start_or_None], [end_or_None])`` matching the ArrayField
    convention on ``Work.timeperiod_*``. JSON-LD ``temporalCoverage`` is
    preferred over ``DC.temporal`` / ``DC.PeriodOfTime``. Open intervals
    (``..``) and missing sides are both surfaced as ``None``.
    """
    parsed = _extract_jsonld_temporal(soup)
    if parsed is None:
        parsed = _extract_dc_temporal(soup)
    if parsed is None:
        return [None], [None]
    start, end = parsed
    return [start], [end]


# -----------------------------------------------------------------------------
# Harvest dedup + careful-update helpers (used by every harvester).
#
# Dedup is per-source: a Work that already exists *under the same Source* is
# the trigger for either skipping or updating. A Work that exists under a
# *different* Source is logged and skipped — OPTIMAP does not currently
# attempt to merge metadata across sources for the same article (see
# docs/manage.md "Deduplication and updates"). Without per-source scoping, the
# Source.{url,doi} model uniqueness would still catch the second insert at
# the DB level, but with an IntegrityError; the explicit pre-check is
# cleaner and lets the caller distinguish same-source vs cross-source.
#
# update_existing=True opts a harvester into in-place updates instead of
# skipping same-source duplicates. The update is *careful*:
#   - geometry / timeperiod_startdate / timeperiod_enddate are preserved
#     if the new harvest delivers nothing for them (the existing values
#     may be user contributions that the source still does not provide);
#   - status and created_by are never overwritten (curation state and
#     audit provenance must survive re-harvest);
#   - provenance.harvest / metadata_sources / openalex_match are refreshed
#     from the new harvest, but provenance.events is preserved and gets
#     a new "harvest_update" entry appended.
# -----------------------------------------------------------------------------

# Fields where the existing value should be preserved when the new harvest
# brings nothing — these are typically populated either by the source itself
# OR by user contributions through OPTIMAP. If the source dropped them this
# round, we don't want to wipe a curator's contribution.
_HARVEST_PRESERVE_IF_NEW_EMPTY = ('geometry', 'timeperiod_startdate', 'timeperiod_enddate')

# Never overwritten on re-harvest — these reflect curation state that a
# fresh harvest has no business touching.
_HARVEST_NEVER_OVERWRITE = ('status', 'created_by', 'creationDate')


def _is_empty_for_update(value):
    """True when a freshly harvested field value carries no information that
    should overwrite an existing one."""
    if value is None:
        return True
    if isinstance(value, list) and not value:
        return True
    if hasattr(value, 'empty') and getattr(value, 'empty'):
        return True
    return False


def _find_existing_work(doi=None, url=None):
    """Return any Work matching ``doi`` or ``url`` (regardless of source).

    Caller decides whether the match is a same-source duplicate (skip or
    update) or a cross-source conflict (skip with a different log message).
    """
    if doi:
        existing = Work.objects.filter(doi=doi).first()
        if existing:
            return existing
    if url:
        existing = Work.objects.filter(url=url).first()
        if existing:
            return existing
    return None


def _carefully_update_work(work, new_fields, event):
    """Update ``work`` in place from re-harvested ``new_fields``, preserving
    curator-added geometry / temporal metadata and the contribution audit
    trail in ``provenance.events``.

    See the module-level comment above this helper for the exact policy.
    """
    new_provenance = new_fields.pop('provenance', None)

    for field, new_value in new_fields.items():
        if field in _HARVEST_NEVER_OVERWRITE:
            continue
        if field in _HARVEST_PRESERVE_IF_NEW_EMPTY and _is_empty_for_update(new_value):
            continue
        setattr(work, field, new_value)

    # Provenance: refresh harvest/metadata_sources/openalex_match from the
    # new harvest, append a harvest_update event, preserve existing events.
    existing_provenance = work.provenance if isinstance(work.provenance, dict) else {}
    if isinstance(new_provenance, dict):
        for key in ('harvest', 'metadata_sources', 'openalex_match'):
            if key in new_provenance:
                existing_provenance[key] = new_provenance[key]
    existing_provenance.setdefault('events', []).append({
        'type': 'harvest_update',
        'at': timezone.now().isoformat(),
        'harvesting_event_id': event.id if event else None,
    })
    work.provenance = existing_provenance

    work.job = event
    work.save()
    return work


def _save_or_update_work(work_kwargs, source, event, update_existing=False):
    """Create or update a Work, applying per-source dedup.

    Returns ``(work_or_none, action)`` where ``action`` is one of:
      * ``'created'`` — new Work was inserted,
      * ``'updated'`` — existing same-source Work was updated in place,
      * ``'skipped_same_source'`` — same-source duplicate, ``update_existing`` was False,
      * ``'skipped_cross_source'`` — different-source duplicate (never auto-merged).
    """
    doi_value = work_kwargs.get('doi')
    url_value = work_kwargs.get('url')

    existing = _find_existing_work(doi=doi_value, url=url_value)
    if existing is not None:
        if existing.source_id != getattr(source, 'id', None):
            logger.info(
                "Skipping cross-source duplicate %s — already harvested under source id=%s",
                doi_value or url_value, existing.source_id,
            )
            return existing, 'skipped_cross_source'
        if not update_existing:
            logger.debug(
                "Skipping same-source duplicate %s (use --update / update_existing=True to refresh)",
                doi_value or url_value,
            )
            return existing, 'skipped_same_source'
        _carefully_update_work(existing, work_kwargs, event)
        return existing, 'updated'

    work = Work.objects.create(**work_kwargs)
    return work, 'created'


def parse_oai_xml_and_save_works(content, event: HarvestingEvent, max_records=None, warning_collector=None, update_existing=False):
    source = event.source
    logger.info("Starting OAI-PMH parsing for source: %s", source.name)
    parsed = urlsplit(source.url_field)

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
    saved_count = 0

    # Calculate progress reporting interval (every 10% of records)
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

            # pick a URL
            http_urls = [u for u in identifiers if u and u.lower().startswith("http")]
            view_urls = [u for u in http_urls if "/view/" in u]
            identifier_value = (view_urls or http_urls or [None])[0]

            # core metadata
            title_value    = get_field("title")       or get_field("dc:title")
            abstract_text  = get_field("description") or get_field("dc:description")
            journal_value  = get_field("publisher")   or get_field("dc:publisher")
            raw_date_value = get_field("date")        or get_field("dc:date")
            date_value     = parse_publication_date(raw_date_value)

            logger.debug("Processing work: %s", title_value[:50] if title_value else 'No title')

            # extract DOI and ISSN
            doi_text = None
            issn_text = None
            for u in identifiers:
                if u and (m := DOI_REGEX.search(u)):
                    doi_text = m.group(0)
                    break

            # Try to extract ISSN from various fields
            issn_candidates = []
            issn_candidates.extend(identifiers)  # Check identifiers
            issn_candidates.append(get_field("source") or get_field("dc:source"))  # Check source field
            issn_candidates.append(get_field("relation") or get_field("dc:relation"))  # Check relation field

            for candidate in issn_candidates:
                if candidate and len(candidate.replace('-', '')) == 8 and candidate.replace('-', '').isdigit():
                    issn_text = candidate
                    break

            # Per-source dedup happens later in _save_or_update_work; cheap pre-check
            # for invalid URLs avoids building unused metadata.
            if not identifier_value or not identifier_value.startswith("http"):
                logger.debug("Skipping invalid URL: %s", identifier_value)
                continue

            # ensure a Source instance for work.source
            src_obj = source  # Default fallback

            if issn_text:
                # First try to match by ISSN
                try:
                    src_obj = Source.objects.get(issn_l=issn_text)
                    logger.debug("Matched source by ISSN %s: %s", issn_text, src_obj.name)
                except Source.DoesNotExist:
                    # Create new source with ISSN if not found
                    if journal_value:
                        src_obj, created = Source.objects.get_or_create(
                            issn_l=issn_text,
                            defaults={'name': journal_value}
                        )
                        if created:
                            logger.debug("Created new source with ISSN %s: %s", issn_text, journal_value)
                    else:
                        src_obj, created = Source.objects.get_or_create(
                            issn_l=issn_text,
                            defaults={'name': f'Unknown Journal (ISSN: {issn_text})'}
                        )
                        if created:
                            logger.debug("Created new source with ISSN %s", issn_text)
            elif journal_value:
                # Fall back to journal name matching
                src_obj, created = Source.objects.get_or_create(name=journal_value)
                if created:
                    logger.debug("Created new source by name: %s", journal_value)

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

            # Extract author metadata from original source
            author_field = get_field("creator") or get_field("dc:creator")
            authors_list = []
            if author_field:
                # Split multiple authors if separated by common delimiters
                authors_list = [a.strip() for a in author_field.replace(';', ',').split(',') if a.strip()]

            # Extract keyword metadata from original source (if available in OAI-PMH)
            subject_field = get_field("subject") or get_field("dc:subject")
            keywords_list = []
            if subject_field:
                # Split multiple keywords if separated by common delimiters
                keywords_list = [k.strip() for k in subject_field.replace(';', ',').split(',') if k.strip()]

            # Prepare existing metadata for OpenAlex matching
            existing_metadata = {}
            if authors_list:
                existing_metadata['authors'] = authors_list
            if keywords_list:
                existing_metadata['keywords'] = keywords_list

            # OpenAlex matching - prioritize existing metadata
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
                    # Get system user for harvested publications
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

                    # Set default type if not provided by OpenAlex
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
                    if action in ('created', 'updated'):
                        # Propagate the harvest's source collection to the work
                        # (no-op when the source has no collection set). The
                        # *event's* source wins over the per-record ISSN-matched
                        # src_obj — the operator's intent for this harvest takes
                        # precedence over per-record source switching.
                        if source and source.collection_id:
                            work.collections.add(source.collection_id)
                    if action == 'created':
                        saved_count += 1
                        logger.info("Saved work id=%s: %s", work.id, title_value[:80] if title_value else 'No title')
                    elif action == 'updated':
                        logger.info("Updated work id=%s: %s", work.id, title_value[:80] if title_value else 'No title')
            except Exception as save_err:
                logger.error("Failed to save work '%s': %s", title_value[:80] if title_value else 'No title', save_err)
                continue

        except Exception as e:
            logger.error("Error parsing record %d: %s", processed_count, e)
            continue

    logger.info("OAI-PMH parsing completed for source %s: processed %d records, saved %d publications",
                source.name, processed_count, saved_count)
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
        backoff_factor=1.5,  # 0s, 1.5s, 3s, 6s
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset(["GET"]),
        respect_retry_after_header=True,
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    session.headers.update({"User-Agent": OAI_USER_AGENT,
                            "Accept": "text/xml, application/xml, */*"})
    return session


def _looks_like_oai_xml(body: bytes) -> bool:
    """Cheap content sniff so we fail fast and clearly when an upstream
    'helpfully' returns an HTML 200 error page instead of an OAI-PMH
    response."""
    if not body:
        return False
    head = body.lstrip()[:512].lower()
    if head.startswith(b"<?xml"):
        return True
    # Some endpoints omit the XML declaration; accept the OAI-PMH root as well.
    return b"<oai-pmh" in head


def _short_body(resp: requests.Response, n: int = 240) -> str:
    """Trim a response body for use in error messages."""
    text = resp.text or ""
    text = " ".join(text.split())  # collapse whitespace for log readability
    if len(text) > n:
        return text[:n] + "…"
    return text


def harvest_oai_endpoint(source_id, user=None, max_records=None, update_existing=False):
    # Admin actions enqueue with a user id rather than a pickled User instance.
    if isinstance(user, int):
        user = User.objects.filter(pk=user).first()

    source = Source.objects.get(id=source_id)
    event  = HarvestingEvent.objects.create(source=source, status="in_progress")

    new_count = None
    spatial_count = None
    temporal_count = None

    # Set up warning collector
    warning_collector = HarvestWarningCollector()
    warning_collector.setLevel(logging.INFO)
    logger.addHandler(warning_collector)

    try:
        # Construct proper OAI-PMH URL
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

        parse_oai_xml_and_save_works(
            response.content, event,
            max_records=max_records,
            warning_collector=warning_collector,
            update_existing=update_existing,
        )

        new_count      = Work.objects.filter(job=event).count()
        spatial_count  = Work.objects.filter(job=event).exclude(geometry__isnull=True).count()
        temporal_count = Work.objects.filter(job=event).exclude(timeperiod_startdate=[]).count()

        event.status                = "completed"
        event.completed_at          = timezone.now()
        event.records_added         = new_count
        event.records_with_spatial  = spatial_count
        event.records_with_temporal = temporal_count
        event.log_text              = warning_collector.get_summary()
        event.save()

        collection_label = source.collection.name if source.collection else source.name
        subject = f"✅ Harvesting Completed for {collection_label}"
        completed_str = event.completed_at.strftime('%Y-%m-%d %H:%M:%S')
        message = (
            f"Harvesting job details:\n\n"
            f"Number of added articles: {new_count}\n"
            f"Number of articles with spatial metadata: {spatial_count}\n"
            f"Number of articles with temporal metadata: {temporal_count}\n"
            f"Collection used: {collection_label}\n"
            f"Journal: {source.url_field}\n"
            f"Job started at: {event.started_at.strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"Job completed at: {completed_str}\n"
        )

        # Add warning summary
        message += f"\n{warning_collector.get_summary()}"

        if user and user.email:
            send_mail(
                subject,
                message,
                settings.EMAIL_HOST_USER,
                [user.email],
                fail_silently=False,
            )
    
    except Exception as e:
        logger.error("Harvesting failed for source %s: %s", source.url_field, str(e))
        event.status        = "failed"
        event.completed_at  = timezone.now()
        event.error_message = str(e)[:1000]
        event.log_text      = warning_collector.get_summary()
        event.save()

        # Send failure notification email to user
        if user and user.email:
            collection_label = source.collection.name if source.collection else source.name
            failure_subject = f"❌ Harvesting Failed for {collection_label}"
            failure_message = (
                f"Unfortunately, the harvesting job failed for the following source:\n\n"
                f"Source: {source.name}\n"
                f"URL: {source.url_field}\n"
                f"Collection: {collection_label}\n"
                f"Job started at: {event.started_at.strftime('%Y-%m-%d %H:%M:%S')}\n"
                f"Job failed at: {event.completed_at.strftime('%Y-%m-%d %H:%M:%S')}\n"
                f"Error details: {str(e)}\n\n"
                f"Please check the source configuration and try again, or contact support if the issue persists."
            )

            # Add warning summary if there were any warnings before the failure
            if warning_collector.has_issues():
                failure_message += f"\n{warning_collector.get_summary()}"

            try:
                send_mail(
                    failure_subject,
                    failure_message,
                    settings.EMAIL_HOST_USER,
                    [user.email],
                    fail_silently=False,
                )
                logger.info("Failure notification email sent to %s", user.email)
            except Exception as email_error:
                logger.error("Failed to send failure notification email: %s", str(email_error))

    finally:
        # Always remove the warning collector handler
        logger.removeHandler(warning_collector)

    return new_count, spatial_count, temporal_count

def send_monthly_email(trigger_source="manual", sent_by=None):
    """
    Send the monthly digest of new manuscripts to users who opted in.

    Rules:
      - One email per distinct recipient with a non-empty address.
      - Link for each work:
          * if DOI present  -> prefer OPTIMAP permalink, fallback to https://doi.org/<doi>
          * else            -> fallback to Work.url (may be empty)
      - Log success/failure to EmailLog.
      - Respect settings.EMAIL_SEND_DELAY if present.
    """
    # Collect distinct, non-empty recipient emails
    recipients_qs = (
        User.objects
        .filter(userprofile__notify_new_manuscripts=True)
        .exclude(email__isnull=True)
        .exclude(email__exact="")
        .values_list("email", flat=True)
        .distinct()
    )
    recipients = list(recipients_qs)

    # Publications created last month (by creationDate month)
    last_month = timezone.now().replace(day=1) - timedelta(days=1)
    new_manuscripts = Work.objects.filter(
        creationDate__year=last_month.year,
        creationDate__month=last_month.month,
    )

    if not recipients or not new_manuscripts.exists():
        return

    # Build message
    def link_for(work):
        """Prefer internal permalink for DOI entries, fall back gracefully."""
        if work.doi:
            try:
                permalink = work.permalink()
            except TypeError:
                # In case permalink was overwritten with a property-like value
                permalink = work.permalink if hasattr(work, "permalink") else None
            if permalink:
                return permalink
            return f"https://doi.org/{work.doi}"
        return work.url or ""

    lines = [f"- {work.title}: {link_for(work)}" for work in new_manuscripts]
    content = "Here are the new manuscripts:\n" + "\n".join(lines)
    subject = "📚 New manuscripts on OPTIMAP"

    # Optional throttle between emails
    delay_seconds = getattr(settings, "EMAIL_SEND_DELAY", 0)

    for recipient in recipients:
        try:
            send_mail(
                subject,
                content,
                settings.EMAIL_HOST_USER,
                [recipient],
                fail_silently=False,
            )
            EmailLog.log_email(
                recipient,
                subject,
                content,
                sent_by=sent_by,
                trigger_source=trigger_source,
                status="success",
            )
            if delay_seconds:
                time.sleep(delay_seconds)
        except Exception as e:
            logger.error("Failed to send monthly email to %s: %s", recipient, e)
            EmailLog.log_email(
                recipient,
                subject,
                content,
                sent_by=sent_by,
                trigger_source=trigger_source,
                status="failed",
                error_message=str(e),
            )


def send_subscription_based_email(trigger_source='manual', sent_by=None, user_ids=None):
    """
    Send subscription-based notifications grouped by region.

    Publications are grouped by the regions the user has subscribed to.
    Each region group includes a link to the region's landing page.
    """
    from works.models import GlobalRegion
    from collections import defaultdict

    query = Subscription.objects.filter(subscribed=True, user__isnull=False).prefetch_related('regions')
    if user_ids:
        query = query.filter(user__id__in=user_ids)

    for subscription in query:
        user_email = subscription.user.email

        # Skip if user has no regions selected
        subscribed_regions = list(subscription.regions.all())
        if not subscribed_regions:
            logger.info(f"Skipping subscription for {user_email} - no regions selected")
            continue

        # Group publications by region
        region_publications = defaultdict(list)
        total_publications = 0

        for region in subscribed_regions:
            # Find publications that intersect with this region
            # Use prepared geometry for performance
            prepared_geom = region.geom.prepared

            candidates = Work.objects.filter(
                status="p",  # Only published works
                geometry__isnull=False,
                geometry__bboverlaps=region.geom,  # Bounding box filter first
            ).order_by('-creationDate')[:50]  # Limit per region

            # Filter by actual intersection
            matching_pubs = [
                work for work in candidates
                if prepared_geom.intersects(work.geometry)
            ]

            if matching_pubs:
                region_publications[region] = matching_pubs
                total_publications += len(matching_pubs)

        # Skip if no new publications found
        if total_publications == 0:
            logger.info(f"Skipping subscription for {user_email} - no new publications")
            continue

        # Build email content grouped by region
        unsubscribe_all = f"{BASE_URL}{reverse('optimap:unsubscribe')}?all=true"
        manage_subscriptions = f"{BASE_URL}{reverse('optimap:subscriptions')}"

        subject = f"🌍 {total_publications} New Publications in Your Subscribed Regions"

        content_lines = [
            f"Dear {subscription.user.username},",
            "",
            f"You have {total_publications} new work(s) in your subscribed regions:",
            ""
        ]

        # Group publications by region
        for region in sorted(region_publications.keys(), key=lambda r: r.name):
            pubs = region_publications[region]
            region_url = f"{BASE_URL}{region.get_absolute_url()}"
            region_type = region.get_region_type_display()

            content_lines.append(f"📍 {region.name} ({region_type}) - {len(pubs)} work(s)")
            content_lines.append(f"   View all publications in this region: {region_url}")
            content_lines.append("")

            for work in pubs[:10]:  # Limit to 10 per region in email
                link = _get_article_link(work)
                title = work.title[:100] + "..." if len(work.title) > 100 else work.title
                content_lines.append(f"   • {title}")
                content_lines.append(f"     {link}")
                content_lines.append("")

            if len(pubs) > 10:
                content_lines.append(f"   ... and {len(pubs) - 10} more in {region.name}")
                content_lines.append(f"   View all: {region_url}")
                content_lines.append("")

        content_lines.extend([
            "───────────────────────────────────────",
            "",
            "Manage your regional subscriptions:",
            f"  {manage_subscriptions}",
            "",
            "Unsubscribe from all notifications:",
            f"  {unsubscribe_all}",
            "",
            "---",
            "OPTIMAP - Open Platform for Geospatial Manuscripts",
            f"{BASE_URL}"
        ])

        content = "\n".join(content_lines)

        try:
            email = EmailMessage(subject, content, settings.EMAIL_HOST_USER, [user_email])
            email.send()
            EmailLog.log_email(user_email, subject, content, sent_by=sent_by, trigger_source=trigger_source, status="success")
            logger.info(f"Sent regional subscription email to {user_email} with {total_publications} publications across {len(region_publications)} regions")
            time.sleep(settings.EMAIL_SEND_DELAY)
        except Exception as e:
            error_message = str(e)
            logger.error(f"Failed to send subscription email to {user_email}: {error_message}")
            EmailLog.log_email(user_email, subject, content, sent_by=sent_by, trigger_source=trigger_source, status="failed", error_message=error_message)


def schedule_monthly_email_task(sent_by=None):
    if not Schedule.objects.filter(func='publications.tasks.send_monthly_email').exists():
        now = datetime.now()
        last_day_of_month = calendar.monthrange(now.year, now.month)[1]
        next_run_date = now.replace(day=last_day_of_month, hour=23, minute=59)
        schedule(
            'publications.tasks.send_monthly_email',
            schedule_type='M',
            repeats=-1,
            next_run=next_run_date,
            kwargs={'trigger_source': 'scheduled', 'sent_by': sent_by.id if sent_by else None} 
        )
        logger.info(f"Scheduled 'schedule_monthly_email_task' for {next_run_date}")


def schedule_subscription_email_task(sent_by=None):
    if not Schedule.objects.filter(func='publications.tasks.send_subscription_based_email').exists():
        now = datetime.now()
        last_day_of_month = calendar.monthrange(now.year, now.month)[1]
        next_run_date = now.replace(day=last_day_of_month, hour=23, minute=59)
        schedule(
            'publications.tasks.send_subscription_based_email',
            schedule_type='M',
            repeats=-1,
            next_run=next_run_date,
            kwargs={'trigger_source': 'scheduled', 'sent_by': sent_by.id if sent_by else None} 
        )
        logger.info(f"Scheduled 'send_subscription_based_email' for {next_run_date}")


def regenerate_geojson_cache():
    cache_dir = os.path.join(tempfile.gettempdir(), "optimap_cache")
    os.makedirs(cache_dir, exist_ok=True)

    json_filename = generate_data_dump_filename("geojson")
    json_path = os.path.join(cache_dir, json_filename)   
    with open(json_path, 'w') as f:
        serialize(
            'geojson',
            Work.objects.filter(status="p"),
            geometry_field='geometry',
            srid=4326,
            stream=f
        )

    gzip_filename = generate_data_dump_filename("geojson.gz")
    gzip_path = os.path.join(cache_dir, gzip_filename)  
    with open(json_path, 'rb') as fin, gzip.open(gzip_path, 'wb') as fout:
        fout.writelines(fin)

    size = os.path.getsize(json_path)
    logger.info("Cached GeoJSON at %s (%d bytes), gzipped at %s", json_path, size, gzip_path)
    # remove old dumps beyond retention
    cleanup_old_data_dumps(Path(cache_dir), settings.DATA_DUMP_RETENTION)
    return json_path


def convert_geojson_to_geopackage(geojson_path):
    cache_dir = os.path.dirname(geojson_path)
    gpkg_filename = generate_data_dump_filename("gpkg")
    gpkg_path = os.path.join(cache_dir, gpkg_filename)    
    try:
        output = subprocess.check_output(
            ["ogr2ogr", "-f", "GPKG", gpkg_path, geojson_path],
            stderr=subprocess.STDOUT,
            text=True,
        )
        logger.info("ogr2ogr output:\n%s", output)
        return gpkg_path
    except subprocess.CalledProcessError:
        return None


def regenerate_geopackage_cache():
    geojson_path = regenerate_geojson_cache()
    cache_dir = Path(geojson_path).parent
    gpkg_path = convert_geojson_to_geopackage(geojson_path)
    cleanup_old_data_dumps(cache_dir, settings.DATA_DUMP_RETENTION)
    return gpkg_path


# ============================================================================
# RSS/Atom Feed Harvesting
# ============================================================================

def parse_rss_feed_and_save_publications(feed_url, event: 'HarvestingEvent', max_records=None, warning_collector=None, update_existing=False):
    """
    Parse RSS/Atom feed and save publications.

    Args:
        feed_url: URL of the RSS/Atom feed
        event: HarvestingEvent instance
        max_records: Maximum number of records to process (optional)
        warning_collector: HarvestWarningCollector instance (optional)

    Returns:
        tuple: (processed_count, saved_count)
    """
    import feedparser

    source = event.source
    logger.info("Starting RSS/Atom feed parsing for source: %s", source.name)

    try:
        # Parse the feed
        feed = feedparser.parse(feed_url)

        if not feed or not hasattr(feed, 'entries'):
            logger.error("Failed to parse RSS feed: %s", feed_url)
            return 0, 0

        entries = feed.entries
        logger.info("Found %d entries in RSS feed", len(entries))

        if not entries:
            logger.warning("No entries found in RSS feed!")
            return 0, 0

        # Limit records if specified
        if max_records:
            entries = entries[:max_records]
            logger.info("Limited to first %d records", max_records)

        processed_count = 0
        saved_count = 0

        # Calculate progress reporting interval (every 10% of entries)
        total_entries = len(entries)
        log_interval = max(1, total_entries // 10)

        for entry in entries:
            try:
                processed_count += 1
                if processed_count % log_interval == 0:
                    logger.debug("Processing entry %d of %d", processed_count, total_entries)

                # Extract metadata from feed entry
                title = entry.get('title', '').strip()
                link = entry.get('link', entry.get('id', '')).strip()

                # Extract DOI - try multiple fields
                doi = None
                if 'prism_doi' in entry:
                    doi = entry.prism_doi.strip()
                elif 'dc_identifier' in entry and 'doi' in entry.dc_identifier.lower():
                    doi_match = DOI_REGEX.search(entry.dc_identifier)
                    if doi_match:
                        doi = doi_match.group(0)

                # Extract date
                published_date = None
                date_str = entry.get('updated', entry.get('published', entry.get('dc_date')))
                if date_str:
                    if hasattr(date_str, 'strftime'):
                        # It's already a datetime
                        published_date = date_str.strftime('%Y-%m-%d')
                    else:
                        # Parse date string
                        published_date = parse_publication_date(str(date_str))

                # Extract abstract/description
                abstract = ''
                if 'summary' in entry:
                    abstract = BeautifulSoup(entry.summary, 'html.parser').get_text()
                elif 'content' in entry and entry.content:
                    abstract = BeautifulSoup(entry.content[0].get('value', ''), 'html.parser').get_text()

                # Skip if no title
                if not title:
                    logger.warning("Skipping entry with no title: %s", link)
                    continue

                # Skip if no URL/identifier
                if not link:
                    logger.warning("Skipping entry '%s' with no URL", title[:50])
                    continue

                logger.debug("Processing work: %s", title[:50])

                # Per-source dedup happens in _save_or_update_work below.

                # Extract author metadata from feed
                author = None
                authors_list = []
                if 'author' in entry:
                    author = entry.author
                    authors_list = [a.strip() for a in author.replace(';', ',').split(',') if a.strip()]
                elif 'dc_creator' in entry:
                    author = entry.dc_creator
                    authors_list = [a.strip() for a in author.replace(';', ',').split(',') if a.strip()]
                elif 'authors' in entry:  # Some feeds have authors as a list
                    authors_list = [a.get('name', '').strip() for a in entry.authors if a.get('name')]
                    author = ', '.join(authors_list) if authors_list else None

                # Extract keyword/tag metadata from feed
                keywords_list = []
                if 'tags' in entry:
                    keywords_list = [tag.get('term', '').strip() for tag in entry.tags if tag.get('term')]
                elif 'categories' in entry:
                    if isinstance(entry.categories, list):
                        keywords_list = [cat.get('term', '').strip() for cat in entry.categories if isinstance(cat, dict) and cat.get('term')]
                elif 'dc_subject' in entry:
                    subject = entry.dc_subject
                    keywords_list = [k.strip() for k in subject.replace(';', ',').split(',') if k.strip()]

                # Prepare existing metadata for OpenAlex matching
                existing_metadata = {}
                if authors_list:
                    existing_metadata['authors'] = authors_list
                if keywords_list:
                    existing_metadata['keywords'] = keywords_list

                # OpenAlex matching - prioritize existing metadata
                openalex_fields, metadata_provenance = build_openalex_fields(
                    title=title,
                    doi=doi,
                    author=author,
                    existing_metadata=existing_metadata
                )

                # Get system user for harvested publications
                admin_user = get_or_create_admin_command_user()

                provenance = {
                    "harvest": {
                        "harvester": "harvest_rss_endpoint",
                        "source_url": feed_url,
                        "source_type": source.source_type,
                        "source_name": source.name,
                        "harvested_at": timezone.now().isoformat(),
                        "harvesting_event_id": event.id,
                    },
                    "metadata_sources": dict(metadata_provenance or {}),
                }

                work_kwargs = dict(
                    title=title,
                    doi=doi,
                    url=link,
                    abstract=abstract[:5000] if abstract else None,
                    publicationDate=published_date,
                    source=source,
                    job=event,
                    timeperiod_startdate=[],
                    timeperiod_enddate=[],
                    geometry=GeometryCollection(),  # No spatial data from RSS typically
                    provenance=provenance,
                    created_by=admin_user,
                    **openalex_fields,
                )
                work, action = _save_or_update_work(
                    work_kwargs, source, event, update_existing=update_existing,
                )
                if action in ('created', 'updated') and source and source.collection_id:
                    work.collections.add(source.collection_id)
                if action == 'created':
                    saved_count += 1
                    logger.debug("Saved work: %s", title[:50])
                elif action == 'updated':
                    logger.debug("Updated work: %s", title[:50])

            except Exception as e:
                logger.error("Failed to process entry '%s': %s",
                           entry.get('title', 'Unknown')[:50], str(e))
                continue

        logger.info("RSS feed parsing completed for source %s: processed %d entries, saved %d publications",
                   source.name, processed_count, saved_count)
        return processed_count, saved_count

    except Exception as e:
        logger.error("Failed to parse RSS feed %s: %s", feed_url, str(e))
        return 0, 0


def harvest_rss_endpoint(source_id, user=None, max_records=None, update_existing=False):
    """
    Harvest publications from an RSS/Atom feed.

    Args:
        source_id: ID of the Source model instance
        user: User who initiated the harvest (optional)
        max_records: Maximum number of records to harvest (optional)
    """
    from works.models import Source, HarvestingEvent, Work

    source = Source.objects.get(id=source_id)
    event = HarvestingEvent.objects.create(source=source, status="in_progress")

    # Set up warning collector
    warning_collector = HarvestWarningCollector()
    warning_collector.setLevel(logging.INFO)
    logger.addHandler(warning_collector)

    try:
        feed_url = source.url_field
        logger.info("Fetching from RSS feed: %s", feed_url)

        processed, saved = parse_rss_feed_and_save_publications(
            feed_url, event,
            max_records=max_records,
            warning_collector=warning_collector,
            update_existing=update_existing,
        )

        event.status = "completed"
        event.completed_at = timezone.now()
        event.save()

        new_count = Work.objects.filter(job=event).count()
        spatial_count = Work.objects.filter(job=event).exclude(geometry__isnull=True).count()
        temporal_count = Work.objects.filter(job=event).exclude(timeperiod_startdate=[]).count()

        subject = f"✅ RSS Feed Harvesting Completed for {source.name}"
        completed_str = event.completed_at.strftime('%Y-%m-%d %H:%M:%S')
        message = (
            f"RSS/Atom feed harvesting job details:\n\n"
            f"Number of added articles: {new_count}\n"
            f"Number of articles with spatial metadata: {spatial_count}\n"
            f"Number of articles with temporal metadata: {temporal_count}\n"
            f"Source: {source.name}\n"
            f"Feed URL: {source.url_field}\n"
            f"Job started at: {event.started_at.strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"Job completed at: {completed_str}\n"
        )

        # Add warning summary
        message += f"\n{warning_collector.get_summary()}"

        if user and user.email:
            send_mail(
                subject,
                message,
                settings.EMAIL_HOST_USER,
                [user.email],
                fail_silently=False,
            )

    except Exception as e:
        logger.error("RSS feed harvesting failed for source %s: %s", source.url_field, str(e))
        event.status = "failed"
        event.completed_at = timezone.now()
        event.save()

        # Send failure notification
        if user and user.email:
            failure_message = (
                f"RSS feed harvesting failed for {source.name}\n\n"
                f"Error: {str(e)}\n\n"
                f"Feed URL: {source.url_field}"
            )

            # Add warning summary if there were any warnings before the failure
            if warning_collector.has_issues():
                failure_message += f"\n{warning_collector.get_summary()}"

            send_mail(
                f"❌ RSS Feed Harvesting Failed for {source.name}",
                failure_message,
                settings.EMAIL_HOST_USER,
                [user.email],
                fail_silently=True,
            )

    finally:
        # Always remove the warning collector handler
        logger.removeHandler(warning_collector)


# ---------------------------------------------------------------------------
# Crossref-prefix harvester (fallback for Copernicus, see issue tracker).
#
# The OAI-PMH endpoint at https://oai-pmh.copernicus.org/oai.php went 404
# sometime between the 2025-12-15 Wayback snapshot and 2026-04-29. While the
# upstream is dark, we can reach the same metadata through Crossref using
# Copernicus's DOI prefix 10.5194 (publisher = "Copernicus GmbH"). The
# trade-off: Crossref supplies <jats:p> abstracts that are usually OK, but
# the publisher-side article landing pages serve the canonical, fully-
# punctuated abstract. This task fetches abstracts directly from the
# journal subdomain by default, falling back to the Crossref payload only
# when the landing-page fetch fails.
# ---------------------------------------------------------------------------

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


def _strip_jats(jats_html):
    """Strip JATS XML tags from a Crossref abstract.

    Crossref returns abstracts wrapped in <jats:p>, with optional
    <jats:italic>, <jats:sub>, etc. inline. We just want the plain text.
    """
    if not jats_html:
        return None
    soup = BeautifulSoup(jats_html, "html.parser")
    return soup.get_text(separator=" ", strip=True) or None


def _build_crossref_filter(prefix, journal_titles=None, since=None):
    """Assemble a Crossref ``filter=...`` parameter value.

    :param prefix: DOI prefix (e.g. "10.5194")
    :param journal_titles: optional iterable of container-title strings
    :param since: optional ISO date string to bound by ``from-update-date``
    """
    parts = [f"prefix:{prefix}"]
    if journal_titles:
        # Crossref lets the same filter key repeat — each title becomes its
        # own clause, and Crossref ORs same-key filters. So a multi-title
        # request widens the result set rather than narrowing it.
        for title in journal_titles:
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
    # Prefer the clean-text <div class="abstract"> over the markup-laden
    # <meta name="citation_abstract">; both carry the same content but the
    # div has the publisher's text formatting collapsed for free.
    div = soup.select_one("div.abstract, div#abstract")
    if div:
        text = div.get_text(separator=" ", strip=True)
        # Drop the literal "Abstract" header that Copernicus prepends.
        if text.lower().startswith("abstract"):
            text = text[len("abstract"):].lstrip(" .:")
        return text or None
    meta = soup.select_one('meta[name="citation_abstract"]')
    if meta and meta.get("content"):
        return BeautifulSoup(meta["content"], "html.parser").get_text(
            separator=" ", strip=True
        ) or None
    return None


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

    # Crossref's "URL" field is the doi.org redirect; resolved-via-Crossref
    # publisher-link is more useful for users.
    url = item.get("URL") or f"https://doi.org/{doi}"
    title_list = item.get("title") or []
    title = title_list[0] if title_list else doi

    # publication date — pick the first defined of published-print /
    # published-online / published / issued.
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
        # The doi.org URL redirects to the journal subdomain landing page.
        abstract = fetch_copernicus_abstract(url, session=abstract_session)
    if not abstract:
        abstract = _strip_jats(item.get("abstract"))

    return {
        "title": title,
        "abstract": abstract,
        "doi": doi,
        "url": url,
        "publicationDate": pub_date,
        "source": source,
        "job": event,
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
            "metadata_sources": {"crossref": "doi"},
        },
        "status": "p",
    }


def parse_crossref_response_and_save_works(
    source, event, prefix, journal_titles=None,
    fetch_abstract_from_publisher=True, max_records=None,
    warning_collector=None, update_existing=False,
):
    """Page through Crossref's ``works`` API and persist matched works.

    Uses cursor-based pagination (``cursor=*`` then echo back), 100 rows per
    page. Stops after ``max_records`` items have been processed (useful for
    smoke tests). Items already present in the DB by DOI are skipped to
    keep the harvest idempotent on re-run.
    """
    session = _crossref_session()
    cursor = "*"
    saved = 0
    seen = 0

    filter_value = _build_crossref_filter(prefix, journal_titles=journal_titles)

    while True:
        params = {
            "filter": filter_value,
            "rows": str(CROSSREF_PAGE_ROWS),
            "cursor": cursor,
            "select": (
                "DOI,title,abstract,published-print,published-online,"
                "published,issued,URL,container-title,publisher"
            ),
        }
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
                if action in ('created', 'updated') and source and source.collection_id:
                    work.collections.add(source.collection_id)
                if action == 'created':
                    saved += 1
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
    journal_titles=None, prefix=None,
    fetch_abstract_from_publisher=True,
    update_existing=False,
):
    """Harvest publications from Crossref by DOI prefix.

    Used as a fallback for Copernicus while their OAI-PMH endpoint is down.

    :param source_id: ID of the Source row
    :param user: optional User to notify on completion / failure
    :param max_records: cap on records processed (debug / smoke tests)
    :param journal_titles: optional list of container-title filters; when
        omitted, every Copernicus journal under the prefix is harvested
    :param prefix: DOI prefix to filter by; falls back to the Source's
        ``crossref_prefix`` attribute and finally to "10.5194" (Copernicus)
    :param fetch_abstract_from_publisher: when True (default), fetch the
        canonical abstract from the journal subdomain landing page rather
        than relying on Crossref's <jats:p> rendering
    """
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
            resolved_prefix, journal_titles, max_records,
        )
        saved, seen = parse_crossref_response_and_save_works(
            source, event,
            prefix=resolved_prefix,
            journal_titles=journal_titles,
            fetch_abstract_from_publisher=fetch_abstract_from_publisher,
            max_records=max_records,
            warning_collector=warning_collector,
            update_existing=update_existing,
        )

        event.status = "completed"
        event.completed_at = timezone.now()
        event.save()

        if user and user.email:
            send_mail(
                f"✅ Crossref Harvesting Completed for {source.name}",
                (
                    f"Crossref harvest details:\n\n"
                    f"DOI prefix: {resolved_prefix}\n"
                    f"Container-title filters: "
                    f"{', '.join(journal_titles) if journal_titles else '<all>'}\n"
                    f"Records seen: {seen}\n"
                    f"New works saved: {saved}\n"
                    f"Started:   {event.started_at:%Y-%m-%d %H:%M:%S}\n"
                    f"Completed: {event.completed_at:%Y-%m-%d %H:%M:%S}\n"
                    f"\n{warning_collector.get_summary()}"
                ),
                settings.EMAIL_HOST_USER,
                [user.email],
                fail_silently=False,
            )

    except Exception as e:
        logger.error(
            "Crossref harvesting failed for source %s: %s",
            source.url_field, str(e),
        )
        event.status = "failed"
        event.completed_at = timezone.now()
        event.save()
        if user and user.email:
            send_mail(
                f"❌ Crossref Harvesting Failed for {source.name}",
                (
                    f"The Crossref harvest failed.\n\n"
                    f"Source: {source.name}\n"
                    f"DOI prefix: {resolved_prefix}\n"
                    f"Error: {e}\n"
                ),
                settings.EMAIL_HOST_USER,
                [user.email],
                fail_silently=True,
            )
        raise
    finally:
        logger.removeHandler(warning_collector)


# -----------------------------------------------------------------------------
# Mountain Wetlands Repository (MaRESS) — bespoke harvester (issue #192).
#
# The MaRESS API at /api/v1/items/ is a Zotero-shaped item dump: every record
# carries a title, a free-text date (often year-only), an abstract, a list of
# `creators` (lastName/firstName), and a list of `study_sites` with point
# coordinates. The DOI and url fields are present in the schema but in the
# 234 records currently exposed they are uniformly null/empty — so OpenAlex
# enrichment is the *only* path to a DOI for this collection. Title +
# first-author surname is the matcher signal; year acts as a sanity check.
# -----------------------------------------------------------------------------

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


def _mwr_item_url(source_url, item_id):
    """Stable per-item URL we use as ``Work.url`` for idempotency.

    Uses the API path so every harvest of the same record collapses onto the
    same row (Work.url is unique).
    """
    base = source_url.rstrip('/').split('?')[0]
    return f"{base.rstrip('/')}/{item_id}"


def _mwr_geometry_from_study_sites(study_sites):
    """Build a ``GeometryCollection`` of points from the API's ``study_sites``."""
    points = []
    for site in study_sites or []:
        loc = site.get('location') or {}
        lat = loc.get('latitude')
        lon = loc.get('longitude')
        if lat is None or lon is None:
            continue
        try:
            lat_f = float(lat)
            lon_f = float(lon)
        except (TypeError, ValueError):
            continue
        if not (-90 <= lat_f <= 90 and -180 <= lon_f <= 180):
            continue
        points.append(Point(lon_f, lat_f, srid=4326))
    if not points:
        return GeometryCollection(srid=4326)
    return GeometryCollection(*points, srid=4326)


def _mwr_first_author_surname(creators):
    """Return the first non-trivial creator surname, or None."""
    for c in creators or []:
        last = (c.get('lastName') or '').strip()
        if not last:
            continue
        if last.lower() in ('et al.', 'et al', 'others'):
            continue
        return last
    return None


def _mwr_authors_list(creators):
    """Build a ``[<First Last>, ...]`` author list from the API record."""
    authors = []
    for c in creators or []:
        last = (c.get('lastName') or '').strip()
        first = (c.get('firstName') or '').strip()
        if last and first:
            authors.append(f"{first} {last}")
        elif last:
            authors.append(last)
    return authors


def _mwr_publication_year(date_str):
    """Parse a year from the API's free-text ``date`` field. Many records have
    only ``"1993"`` etc., so we don't try to recover month/day. Returns a
    ``datetime.date`` (Jan 1 of the year) or ``None``."""
    if not date_str:
        return None
    s = str(date_str).strip()
    if not s:
        return None
    try:
        year = int(s[:4])
    except ValueError:
        return None
    if not (1500 <= year <= 2100):
        return None
    return date(year, 1, 1)


def parse_mountain_wetlands_response_and_save_works(
    payload, source, event, max_records=None, processed_so_far=0, warning_collector=None,
    update_existing=False,
):
    """Save one page of MaRESS items. Returns ``(saved, processed)`` for this page."""
    items = payload.get('data') or []
    saved = 0
    processed = 0
    admin_user = get_or_create_admin_command_user()

    for item in items:
        if max_records and (processed_so_far + processed) >= max_records:
            break
        processed += 1

        item_id = item.get('id')
        title = (item.get('title') or '').strip()
        if not title:
            logger.info("Skipping MaRESS item with no title (id=%s)", item_id)
            continue
        if not item_id:
            logger.info("Skipping MaRESS item with no id: %s", title[:60])
            continue

        item_url = _mwr_item_url(source.url_field, item_id)
        # Per-source dedup happens in _save_or_update_work below.

        creators = item.get('creators') or []
        api_authors = _mwr_authors_list(creators)
        first_author_surname = _mwr_first_author_surname(creators)
        pub_date = _mwr_publication_year(item.get('date'))
        geom_obj = _mwr_geometry_from_study_sites(item.get('study_sites'))
        abstract = (item.get('abstractNote') or None) or None

        existing_metadata = {}
        if api_authors:
            existing_metadata['authors'] = api_authors

        # OpenAlex enrichment — DOI is None for every MaRESS record, so
        # title+author is the only available signal.
        openalex_fields, metadata_provenance = build_openalex_fields(
            title=title,
            doi=None,
            author=first_author_surname,
            existing_metadata=existing_metadata,
        )

        # Match status: 'verified' if the matcher returned a strong title+author
        # match, 'candidate' if only partial matches surfaced, 'none' otherwise.
        if openalex_fields.get('openalex_id'):
            match_status = 'verified'
        elif openalex_fields.get('openalex_match_info'):
            match_status = 'candidate'
        else:
            match_status = 'none'

        # Pull the DOI out of OpenAlex IDs when verified — issue #192 explicitly
        # asks the harvester to recover DOIs from OpenAlex by title.
        # Per-source dedup on this DOI is handled by _save_or_update_work below.
        doi_value = None
        ids_blob = openalex_fields.get('openalex_ids') or {}
        if match_status == 'verified' and ids_blob.get('doi'):
            raw = ids_blob['doi']
            doi_value = raw.split('doi.org/', 1)[-1].lstrip('/') if 'doi.org/' in raw else raw.lstrip('/')

        if not metadata_provenance.get('authors') and api_authors:
            metadata_provenance['authors'] = 'original_source'
        metadata_provenance['geometry'] = 'study_sites' if not geom_obj.empty else None
        metadata_provenance['date'] = 'original_source (year-only)' if pub_date else None

        provenance = {
            'harvest': {
                'harvester': 'harvest_mountain_wetlands',
                'source_url': source.url_field,
                'source_type': source.source_type,
                'source_name': source.name,
                'harvested_at': timezone.now().isoformat(),
                'harvesting_event_id': event.id,
                'external_id': item_id,
                'original_record': item,
            },
            'metadata_sources': {k: v for k, v in metadata_provenance.items() if v is not None},
            'openalex_match': {
                'status': match_status,
                'matched_id': openalex_fields.get('openalex_id'),
                'first_author_surname_used': first_author_surname,
            },
        }

        # Default the work type from the source if OpenAlex didn't pick one.
        if 'type' not in openalex_fields:
            openalex_fields['type'] = source.default_work_type or 'article'

        try:
            work_kwargs = dict(
                title=title,
                abstract=abstract,
                publicationDate=pub_date,
                url=item_url,
                doi=doi_value,
                source=source,
                status='h',
                geometry=geom_obj,
                timeperiod_startdate=[str(pub_date.year)] if pub_date else [],
                timeperiod_enddate=[str(pub_date.year)] if pub_date else [],
                job=event,
                provenance=provenance,
                created_by=admin_user,
                **openalex_fields,
            )
            work, action = _save_or_update_work(
                work_kwargs, source, event, update_existing=update_existing,
            )
            if action in ('created', 'updated') and source.collection_id:
                work.collections.add(source.collection_id)
            if action == 'created':
                saved += 1
                logger.info(
                    "Saved MaRESS work id=%s (%s) status=%s",
                    work.id, item_id, match_status,
                )
            elif action == 'updated':
                logger.info(
                    "Updated MaRESS work id=%s (%s) status=%s",
                    work.id, item_id, match_status,
                )
        except Exception as save_err:
            logger.warning("Failed to save MaRESS item %s: %s", item_id, save_err)
            continue

    return saved, processed


def harvest_mountain_wetlands(source_id, user=None, max_records=None, update_existing=False):
    """Bespoke harvester for the Mountain Wetlands Repository (MaRESS API).

    Manual-only — the issue #192 explicitly forbids auto-scheduling. Run via
    ``python manage.py harvest_journals --journal mountain-wetlands`` or via
    the Django admin "Trigger harvesting" action.
    """
    if isinstance(user, int):
        user = User.objects.filter(pk=user).first()

    source = Source.objects.get(id=source_id)
    event = HarvestingEvent.objects.create(source=source, status='in_progress')

    warning_collector = HarvestWarningCollector()
    warning_collector.setLevel(logging.INFO)
    logger.addHandler(warning_collector)

    total_saved = 0
    total_processed = 0
    try:
        session = _mwr_session()
        skip = 0
        base_url = source.url_field.split('?')[0]
        while True:
            params = {'limit': MWR_PAGE_SIZE, 'skip': skip, 'scope': 'all'}
            logger.info("Fetching MaRESS items: skip=%d limit=%d", skip, MWR_PAGE_SIZE)
            try:
                response = session.get(base_url, params=params, timeout=MWR_HTTP_TIMEOUT)
            except requests.exceptions.RequestException as e:
                raise RuntimeError(f"MaRESS request failed for {base_url}: {e}") from e
            if not response.ok:
                raise RuntimeError(
                    f"MaRESS endpoint returned HTTP {response.status_code} for {base_url} "
                    f"(skip={skip}). Body preview: {_short_body(response)}"
                )
            try:
                payload = response.json()
            except ValueError as e:
                raise RuntimeError(f"MaRESS response was not valid JSON: {e}") from e

            saved, processed = parse_mountain_wetlands_response_and_save_works(
                payload, source, event,
                max_records=max_records,
                processed_so_far=total_processed,
                warning_collector=warning_collector,
                update_existing=update_existing,
            )
            total_saved += saved
            total_processed += processed

            count = payload.get('count') or 0
            page_data = payload.get('data') or []
            # Stop conditions: no items returned, hit max_records, or paged past count.
            if not page_data:
                break
            if max_records and total_processed >= max_records:
                break
            skip += MWR_PAGE_SIZE
            if skip >= count:
                break

        # Refresh counts off the DB.
        spatial_count = (
            Work.objects.filter(job=event)
            .exclude(geometry__isnull=True)
            .exclude(geometry__exact=GEOSGeometry('GEOMETRYCOLLECTION EMPTY'))
            .count()
        )
        temporal_count = Work.objects.filter(job=event).exclude(timeperiod_startdate=[]).count()

        event.status = 'completed'
        event.completed_at = timezone.now()
        event.records_added = total_saved
        event.records_with_spatial = spatial_count
        event.records_with_temporal = temporal_count
        event.log_text = warning_collector.get_summary()
        event.save()

        if user and user.email:
            collection_label = source.collection.name if source.collection else source.name
            send_mail(
                f"✅ Harvesting Completed for {collection_label}",
                (
                    f"MaRESS harvest details:\n\n"
                    f"Source: {source.name}\n"
                    f"URL: {source.url_field}\n"
                    f"Records processed: {total_processed}\n"
                    f"New works saved: {total_saved}\n"
                    f"With spatial extent: {spatial_count}\n"
                    f"With temporal extent: {temporal_count}\n"
                    f"Started:   {event.started_at:%Y-%m-%d %H:%M:%S}\n"
                    f"Completed: {event.completed_at:%Y-%m-%d %H:%M:%S}\n"
                    f"\n{warning_collector.get_summary()}"
                ),
                settings.EMAIL_HOST_USER,
                [user.email],
                fail_silently=False,
            )

    except Exception as e:
        logger.error(
            "MaRESS harvesting failed for source %s: %s", source.url_field, str(e),
        )
        event.status = 'failed'
        event.completed_at = timezone.now()
        event.error_message = str(e)[:1000]
        event.log_text = warning_collector.get_summary()
        event.save()
        if user and user.email:
            send_mail(
                f"❌ Harvesting Failed for {source.name}",
                (
                    f"The MaRESS harvest failed.\n\n"
                    f"Source: {source.name}\n"
                    f"URL: {source.url_field}\n"
                    f"Error: {e}\n"
                    f"\n{warning_collector.get_summary()}"
                ),
                settings.EMAIL_HOST_USER,
                [user.email],
                fail_silently=True,
            )
        raise
    finally:
        logger.removeHandler(warning_collector)

    return total_saved, total_processed
