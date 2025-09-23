mport logging
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

logger = logging.getLogger(__name__)
BASE_URL = settings.BASE_URL
DOI_REGEX = re.compile(r'10\.\d{4,9}/[-._;()/:A-Z0-9]+', re.IGNORECASE)
CACHE_DIR = Path(tempfile.gettempdir()) / 'optimap_cache'

def _get_article_link(pub):
    """Prefer our site permalink if DOI exists, else fallback to original URL."""
    if getattr(pub, "doi", None):
        base = settings.BASE_URL.rstrip("/")
        return f"{base}/work/{pub.doi}"
    return pub.url
    
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
    return [None], [None]
            return ([start] if start else [None]), ([end] if end else [None]) # If missing, return [None] for start and [None] for end


def parse_oai_xml_and_save_publications(content, event: HarvestingEvent, max_records=None):
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

    for rec in records:
        try:
            processed_count += 1
            if processed_count % 10 == 0:
                logger.debug("Processing record %d of %d", processed_count, len(records) if hasattr(records, '__len__') else '?')

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
            date_value     = get_field("date")        or get_field("dc:date")

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

            try:
                with transaction.atomic():
                    pub = Publication.objects.create(
                        title                = title_value,
                        abstract             = abstract_text,
                        publicationDate      = date_value,
                        url                  = identifier_value,
                        doi                  = doi_text,
                        source               = src_obj,
                        status               = "p",
                        geometry             = geom_obj,
                        timeperiod_startdate = period_start,
                        timeperiod_enddate   = period_end,
                        job                  = event,
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

    try:
        # Construct proper OAI-PMH URL
        if '?' not in source.url_field:
            oai_url = f"{source.url_field}?verb=ListRecords&metadataPrefix=oai_dc"
        else:
            oai_url = source.url_field

        logger.info("Fetching from OAI-PMH URL: %s", oai_url)
        response = requests.get(oai_url)
        response.raise_for_status()

        parse_oai_xml_and_save_publications(response.content, event, max_records=max_records)

        event.status      = "completed"
        event.completed_at = timezone.now()
        event.save()
        
        new_count      = Publication.objects.filter(job=event).count()
        spatial_count  = Publication.objects.filter(job=event).exclude(geometry__isnull=True).count()
        temporal_count = Publication.objects.filter(job=event).exclude(timeperiod_startdate=[]).count()
        
        subject = f"Harvesting Completed for {source.collection_name}"
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
        
        if user and user.email:
            send_mail(
                subject,
                message,
                settings.EMAIL_HOST_USER,
                [user.email],
                fail_silently=False,
            )
        
        return new_count, spatial_count, temporal_count
    except Exception as e:
        logger.error("Harvesting failed for source %s: %s", source.url_field, str(e))
        event.status = "failed"
        event.completed_at = timezone.now()
        event.save()

        # Send failure notification email to user
        if user and user.email:
            failure_subject = f"Harvesting Failed for {source.collection_name or source.name}"
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

        return None, None, None


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
    query = Subscription.objects.filter(subscribed=True, user__isnull=False)
    if user_ids:
        query = query.filter(user__id__in=user_ids)

    for subscription in query:
        user_email = subscription.user.email
        new_publications = Publication.objects.filter(geometry__intersects=subscription.region)
        if not new_publications.exists():
            continue

        unsubscribe_specific = f"{BASE_URL}{reverse('optimap:unsubscribe')}?search={quote(subscription.search_term)}"
        unsubscribe_all = f"{BASE_URL}{reverse('optimap:unsubscribe')}?all=true"
        subject = f"📚 New Manuscripts Matching '{subscription.search_term}'"

        lines = []
        for pub in new_publications:
            link = _get_article_link(pub)
            lines.append(f"- {pub.title}: {link}")
        bullet_list = "\n".join(lines)

        content = f"""Dear {subscription.user.username},
        {bullet_list}
        Here are the latest manuscripts matching your subscription:
        Manage your subscriptions:
        Unsubscribe from '{subscription.search_term}': {unsubscribe_specific}
        Unsubscribe from All: {unsubscribe_all}
        """

        try:
            email = EmailMessage(subject, content, settings.EMAIL_HOST_USER, [user_email])
            email.send()
            EmailLog.log_email(user_email, subject, content, sent_by=sent_by, trigger_source=trigger_source, status="success")
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


def regenerate_geopackage_cache():    return new_count, spatial_count, temporal_count

    geojson_path = regenerate_geojson_cache()
    cache_dir = Path(geojson_path).parent
    gpkg_path = convert_geojson_to_geopackage(geojson_path)
    cleanup_old_data_dumps(cache_dir, settings.DATA_DUMP_RETENTION)
    return gpkg_path
