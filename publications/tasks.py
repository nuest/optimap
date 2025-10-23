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
from datetime import datetime, timedelta, timezone as dt_timezone
from urllib.parse import urlsplit, urlunsplit, quote
import xml.dom.minidom

import requests
from pathlib import Path
from bs4 import BeautifulSoup
from xml.dom import minidom

from urllib.parse import quote
from django.conf import settings
from django.core.serializers import serialize
from django.core.mail import send_mail, EmailMessage
from django.utils import timezone
from django.db import transaction
from django.contrib.gis.geos import GEOSGeometry, GeometryCollection
from django_q.tasks import schedule
from django_q.models import Schedule
from django.contrib.auth import get_user_model
from publications.models import Publication, HarvestingEvent, Source, EmailLog, Subscription
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
    Match a publication against OpenAlex and return the appropriate fields dictionary.

    This function prioritizes existing metadata from the original source and only fills
    in missing information from OpenAlex.

    Args:
        title: Publication title (required)
        doi: Publication DOI (optional)
        author: Publication author (optional)
        existing_metadata: Dict of metadata already extracted from original source (optional)

    Returns:
        tuple: (openalex_fields dict, metadata_provenance dict)
              openalex_fields: Dictionary containing fields to be unpacked into Publication.objects.create()
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
                logger.warning("No OpenAlex match for publication with DOI %s: %s", doi, title[:50] if title else 'No title')
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


def _get_article_link(pub):
    """Prefer our site permalink if DOI exists, else fallback to original URL."""
    if getattr(pub, "doi", None):
        base = settings.BASE_URL.rstrip("/")
        return f"{base}/work/{pub.doi}"
    return pub.url
    

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


def extract_geometry_from_html(soup: BeautifulSoup):
    for tag in soup.find_all("meta"):
        if tag.get("name") == "DC.SpatialCoverage":
            try:
                geom = json.loads(tag["content"])
                geom_data = geom["features"][0]["geometry"]
                coll = {"type": "GeometryCollection", "geometries": [geom_data]}
                return GEOSGeometry(json.dumps(coll))
            except Exception:
                pass
    return None


def extract_timeperiod_from_html(soup: BeautifulSoup):
    for tag in soup.find_all("meta"):
        if tag.get("name") in ("DC.temporal", "DC.PeriodOfTime"):
            parts = tag["content"].split("/")
            end   = parts[1] if len(parts) > 1 and parts[1] else None
            start = parts[0] if parts[0] else None
            return ([start] if start else [None]), ([end] if end else [None]) # If missing, return [None] for start and [None] for end
    return [None], [None]


def parse_oai_xml_and_save_publications(content, event: HarvestingEvent, max_records=None, warning_collector=None):
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

            logger.debug("Processing publication: %s", title_value[:50] if title_value else 'No title')

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

            # skip duplicates
            if doi_text and Publication.objects.filter(doi=doi_text).exists():
                logger.debug("Skipping duplicate (DOI): %s", doi_text)
                continue
            if identifier_value and Publication.objects.filter(url=identifier_value).exists():
                logger.debug("Skipping duplicate (URL): %s", identifier_value)
                continue
            if not identifier_value or not identifier_value.startswith("http"):
                logger.debug("Skipping invalid URL: %s", identifier_value)
                continue

            # ensure a Source instance for publication.source
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
            try:
                logger.debug("Fetching HTML content for geometry extraction: %s", identifier_value)
                resp = requests.get(identifier_value, timeout=10)
                resp.raise_for_status()
                soup = BeautifulSoup(resp.content, "html.parser")
                if extracted := extract_geometry_from_html(soup):
                    geom_obj = extracted
                    logger.debug("Extracted geometry from HTML for: %s", identifier_value)
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

            try:
                with transaction.atomic():
                    # Get system user for harvested publications
                    admin_user = get_or_create_admin_command_user()

                    # Build structured provenance including metadata sources
                    harvest_timestamp = timezone.now().isoformat()
                    provenance_parts = [
                        f"Harvested via OAI-PMH from {source.name} (URL: {source.url_field}) on {harvest_timestamp}.",
                        f"HarvestingEvent ID: {event.id}."
                    ]

                    # Add metadata source tracking
                    if metadata_provenance:
                        provenance_parts.append("\nMetadata Sources:")
                        for field, source_type in metadata_provenance.items():
                            provenance_parts.append(f"  - {field}: {source_type}")

                    provenance = "\n".join(provenance_parts)

                    pub = Publication.objects.create(
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
                        # OpenAlex fields
                        **openalex_fields
                    )
                    saved_count += 1
                    logger.info("Saved publication id=%s: %s", pub.id, title_value[:80] if title_value else 'No title')
            except Exception as save_err:
                logger.error("Failed to save publication '%s': %s", title_value[:80] if title_value else 'No title', save_err)
                continue

        except Exception as e:
            logger.error("Error parsing record %d: %s", processed_count, e)
            continue

    logger.info("OAI-PMH parsing completed for source %s: processed %d records, saved %d publications",
                source.name, processed_count, saved_count)
def harvest_oai_endpoint(source_id, user=None, max_records=None):
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
        response = requests.get(oai_url)
        response.raise_for_status()

        parse_oai_xml_and_save_publications(response.content, event, max_records=max_records, warning_collector=warning_collector)

        event.status      = "completed"
        event.completed_at = timezone.now()
        event.save()

        new_count      = Publication.objects.filter(job=event).count()
        spatial_count  = Publication.objects.filter(job=event).exclude(geometry__isnull=True).count()
        temporal_count = Publication.objects.filter(job=event).exclude(timeperiod_startdate=[]).count()

        subject = f"✅ Harvesting Completed for {source.collection_name}"
        completed_str = event.completed_at.strftime('%Y-%m-%d %H:%M:%S')
        message = (
            f"Harvesting job details:\n\n"
            f"Number of added articles: {new_count}\n"
            f"Number of articles with spatial metadata: {spatial_count}\n"
            f"Number of articles with temporal metadata: {temporal_count}\n"
            f"Collection used: {source.collection_name or 'N/A'}\n"
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
        event.status = "failed"
        event.completed_at = timezone.now()
        event.save()

        # Send failure notification email to user
        if user and user.email:
            failure_subject = f"❌ Harvesting Failed for {source.collection_name or source.name}"
            failure_message = (
                f"Unfortunately, the harvesting job failed for the following source:\n\n"
                f"Source: {source.name}\n"
                f"URL: {source.url_field}\n"
                f"Collection: {source.collection_name or 'N/A'}\n"
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
      - Link for each publication:
          * if DOI present  -> prefer OPTIMAP permalink, fallback to https://doi.org/<doi>
          * else            -> fallback to Publication.url (may be empty)
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
    new_manuscripts = Publication.objects.filter(
        creationDate__year=last_month.year,
        creationDate__month=last_month.month,
    )

    if not recipients or not new_manuscripts.exists():
        return

    # Build message
    def link_for(pub):
        """Prefer internal permalink for DOI entries, fall back gracefully."""
        if pub.doi:
            try:
                permalink = pub.permalink()
            except TypeError:
                # In case permalink was overwritten with a property-like value
                permalink = pub.permalink if hasattr(pub, "permalink") else None
            if permalink:
                return permalink
            return f"https://doi.org/{pub.doi}"
        return pub.url or ""

    lines = [f"- {pub.title}: {link_for(pub)}" for pub in new_manuscripts]
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
    from publications.models import GlobalRegion
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

            candidates = Publication.objects.filter(
                status="p",  # Only published works
                geometry__isnull=False,
                geometry__bboverlaps=region.geom,  # Bounding box filter first
            ).order_by('-creationDate')[:50]  # Limit per region

            # Filter by actual intersection
            matching_pubs = [
                pub for pub in candidates
                if prepared_geom.intersects(pub.geometry)
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
            f"You have {total_publications} new publication(s) in your subscribed regions:",
            ""
        ]

        # Group publications by region
        for region in sorted(region_publications.keys(), key=lambda r: r.name):
            pubs = region_publications[region]
            region_url = f"{BASE_URL}{region.get_absolute_url()}"
            region_type = region.get_region_type_display()

            content_lines.append(f"📍 {region.name} ({region_type}) - {len(pubs)} publication(s)")
            content_lines.append(f"   View all publications in this region: {region_url}")
            content_lines.append("")

            for pub in pubs[:10]:  # Limit to 10 per region in email
                link = _get_article_link(pub)
                title = pub.title[:100] + "..." if len(pub.title) > 100 else pub.title
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
            Publication.objects.filter(status="p"),
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

def parse_rss_feed_and_save_publications(feed_url, event: 'HarvestingEvent', max_records=None, warning_collector=None):
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

                logger.debug("Processing publication: %s", title[:50])

                # Check for duplicates by DOI or URL
                existing_pub = None
                if doi:
                    existing_pub = Publication.objects.filter(doi=doi).first()
                if not existing_pub and link:
                    existing_pub = Publication.objects.filter(url=link).first()

                if existing_pub:
                    logger.debug("Publication already exists: %s", title[:50])
                    continue

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

                # Build structured provenance including metadata sources
                harvest_timestamp = timezone.now().isoformat()
                provenance_parts = [
                    f"Harvested via RSS/Atom feed from {source.name} (URL: {feed_url}) on {harvest_timestamp}.",
                    f"HarvestingEvent ID: {event.id}."
                ]

                # Add metadata source tracking
                if metadata_provenance:
                    provenance_parts.append("\nMetadata Sources:")
                    for field, source_type in metadata_provenance.items():
                        provenance_parts.append(f"  - {field}: {source_type}")

                provenance = "\n".join(provenance_parts)

                # Create publication
                pub = Publication(
                    title=title,
                    doi=doi,
                    url=link,
                    abstract=abstract[:5000] if abstract else None,  # Limit abstract length
                    publicationDate=published_date,
                    source=source,
                    job=event,
                    timeperiod_startdate=[],
                    timeperiod_enddate=[],
                    geometry=GeometryCollection(),  # No spatial data from RSS typically
                    provenance=provenance,
                    created_by=admin_user,
                    # OpenAlex fields
                    **openalex_fields
                )

                pub.save()
                saved_count += 1
                logger.debug("Saved publication: %s", title[:50])

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


def harvest_rss_endpoint(source_id, user=None, max_records=None):
    """
    Harvest publications from an RSS/Atom feed.

    Args:
        source_id: ID of the Source model instance
        user: User who initiated the harvest (optional)
        max_records: Maximum number of records to harvest (optional)
    """
    from publications.models import Source, HarvestingEvent, Publication

    source = Source.objects.get(id=source_id)
    event = HarvestingEvent.objects.create(source=source, status="in_progress")

    # Set up warning collector
    warning_collector = HarvestWarningCollector()
    warning_collector.setLevel(logging.INFO)
    logger.addHandler(warning_collector)

    try:
        feed_url = source.url_field
        logger.info("Fetching from RSS feed: %s", feed_url)

        processed, saved = parse_rss_feed_and_save_publications(feed_url, event, max_records=max_records, warning_collector=warning_collector)

        event.status = "completed"
        event.completed_at = timezone.now()
        event.save()

        new_count = Publication.objects.filter(job=event).count()
        spatial_count = Publication.objects.filter(job=event).exclude(geometry__isnull=True).count()
        temporal_count = Publication.objects.filter(job=event).exclude(timeperiod_startdate=[]).count()

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
