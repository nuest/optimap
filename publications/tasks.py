import logging

logger = logging.getLogger(__name__)
import os
import json
import subprocess
import gzip
import re
import tempfile
import time
import calendar
from datetime import datetime, timedelta
import xml.dom.minidom

import requests
from bs4 import BeautifulSoup
from requests.auth import HTTPBasicAuth
from urllib.parse import quote

from django.conf import settings
from django.core.mail import send_mail, EmailMessage
from django.core.serializers import serialize
from django.contrib.gis.geos import GEOSGeometry
from django.utils import timezone
from django_q.tasks import schedule
from django_q.models import Schedule

from publications.models import Publication, HarvestingEvent, Source
from .models import EmailLog, Subscription
from django.contrib.auth import get_user_model
from django.urls import reverse

User = get_user_model()
BASE_URL = settings.BASE_URL

DOI_REGEX = re.compile(r'10\.\d{4,9}/[-._;()/:A-Z0-9]+', re.IGNORECASE)


def extract_geometry_from_html(content):
    for tag in content.find_all("meta"):
        if tag.get("name") == "DC.SpatialCoverage":
            data = tag.get("content")
            try:
                geom = json.loads(data)
                geom_data = geom["features"][0]["geometry"]
                feature_collection = {
                    'type': 'GeometryCollection',
                    'geometries': [geom_data]
                }
                geom_string = json.dumps(feature_collection)
                try:
                    return GEOSGeometry(geom_string)
                except Exception as e:
                    logger.error("Invalid GEOS geometry: %s", e)
                    return None
            except ValueError as e:
                logger.error("Invalid JSON in DC.SpatialCoverage: %s", e)
                return None
    return None


def extract_timeperiod_from_html(content):
    """Extract DC.temporal or DC.PeriodOfTime (start/end) from HTML meta."""
    for tag in content.find_all("meta"):
        if tag.get("name") in ['DC.temporal', 'DC.PeriodOfTime']:
            data = tag.get("content", "")
            parts = data.split("/")
            start = parts[0] if parts else None
            end = parts[1] if len(parts) > 1 else None
            return [start], [end]
    return [None], [None]


def parse_oai_xml_and_save_publications(content, event):
    DOM = xml.dom.minidom.parseString(content)
    records = DOM.getElementsByTagName("record")
    if not records:
        logger.warning("No records in OAI response")
        return

    existing_urls = set(Publication.objects.values_list('url', flat=True))
    existing_dois = set(
        Publication.objects.exclude(doi__isnull=True).values_list('doi', flat=True)
    )

    for record in records:
        try:
            def get_text(tag):
                nodes = record.getElementsByTagName(tag)
                return (nodes[0].firstChild.nodeValue.strip()
                        if nodes and nodes[0].firstChild else None)

            identifier = get_text("dc:identifier")
            if not identifier or not identifier.startswith("http"):
                logger.warning("Bad identifier: %s", identifier)
                continue

            doi = None
            for node in record.getElementsByTagName("dc:identifier"):
                val = node.firstChild.nodeValue.strip() if node.firstChild else ""
                m = DOI_REGEX.search(val)
                if m:
                    doi = m.group(0)
                    break

            if doi and doi in existing_dois:
                logger.info("Duplicate DOI: %s", doi)
                continue
            if identifier in existing_urls:
                logger.info("Duplicate URL: %s", identifier)
                continue

            # fetch HTML for geometry + period
            geom_obj, period_start, period_end = None, [None], [None]
            try:
                r = requests.get(identifier)
                r.raise_for_status()
                soup = BeautifulSoup(r.content, "html.parser")
                geom_obj = extract_geometry_from_html(soup)
                period_start, period_end = extract_timeperiod_from_html(soup)
            except Exception as err:
                logger.error("Error scraping %s: %s", identifier, err)

            pub = Publication(
                title=get_text("dc:title"),
                abstract=get_text("dc:description"),
                publicationDate=get_text("dc:date"),
                url=identifier,
                doi=doi,
                source=get_text("dc:publisher"),
                geometry=geom_obj,
                timeperiod_startdate=period_start,
                timeperiod_enddate=period_end
            )
            pub.save()
            logger.info("Saved publication: %s", identifier)

            existing_urls.add(identifier)
            if doi:
                existing_dois.add(doi)

        except Exception as e:
            logger.error("Failed record parse: %s", e)
            continue


def harvest_oai_endpoint(source_id):
    source = Source.objects.get(id=source_id)
    event = HarvestingEvent.objects.create(source=source, status="in_progress")
    username = os.getenv("OPTIMAP_OAI_USERNAME")
    password = os.getenv("OPTIMAP_OAI_PASSWORD")

    try:
        r = requests.get(source.url_field, auth=HTTPBasicAuth(username, password))
        r.raise_for_status()
        parse_oai_xml_and_save_publications(r.content, event)
        event.status = "completed"
    except Exception as e:
        logger.error("Harvest error: %s", e)
        event.status = "failed"
        event.log = str(e)
    finally:
        event.completed_at = timezone.now()
        event.save()


def send_monthly_email(trigger_source='manual', sent_by=None):
    last_month = timezone.now().replace(day=1) - timedelta(days=1)
    recipients = User.objects.filter(
        userprofile__notify_new_manuscripts=True
    ).values_list('email', flat=True)
    new_pubs = Publication.objects.filter(
        creationDate__month=last_month.month
    )

    if not recipients or not new_pubs.exists():
        return

    subject = "📚 New Manuscripts This Month"
    body = "\n".join([pub.title for pub in new_pubs])
    for email in recipients:
        try:
            send_mail(subject, body, settings.EMAIL_HOST_USER, [email])
            EmailLog.log_email(
                email, subject, body,
                sent_by=sent_by, trigger_source=trigger_source, status="success"
            )
            time.sleep(settings.EMAIL_SEND_DELAY)
        except Exception as ex:
            logger.error("Email failed for %s: %s", email, ex)
            EmailLog.log_email(
                email, subject, body,
                sent_by=sent_by, trigger_source=trigger_source,
                status="failed", error_message=str(ex)
            )


def send_subscription_based_email(trigger_source='manual', sent_by=None, user_ids=None):
    subs = Subscription.objects.filter(subscribed=True, user__isnull=False)
    if user_ids:
        subs = subs.filter(user__id__in=user_ids)

    for sub in subs:
        pubs = Publication.objects.filter(geometry__intersects=sub.region)
        if not pubs.exists():
            continue

        bullet = "\n".join(f"- {p.title}" for p in pubs)
        unsub_one = f"{BASE_URL}{reverse('optimap:unsubscribe')}?search={quote(sub.search_term)}"
        unsub_all = f"{BASE_URL}{reverse('optimap:unsubscribe')}?all=true"
        content = (
            f"Dear {sub.user.username},\n"
            f"{bullet}\n"
            f"Unsubscribe here: {unsub_one}\n"
            f"Unsubscribe all: {unsub_all}\n"
        )
        try:
            EmailMessage(
                f"📚 New Manuscripts for '{sub.search_term}'",
                content, settings.EMAIL_HOST_USER, [sub.user.email]
            ).send()
            EmailLog.log_email(
                sub.user.email,
                f"📚 New Manuscripts for '{sub.search_term}'",
                content, sent_by, trigger_source, status="success"
            )
            time.sleep(settings.EMAIL_SEND_DELAY)
        except Exception as e:
            logger.error("Subscription email failed: %s", e)
            EmailLog.log_email(
                sub.user.email,
                f"📚 New Manuscripts for '{sub.search_term}'",
                content, sent_by, trigger_source,
                status="failed", error_message=str(e)
            )


def schedule_monthly_email_task(sent_by=None):
    if not Schedule.objects.filter(func='publications.tasks.send_monthly_email').exists():
        now_dt = datetime.now()
        last_day = calendar.monthrange(now_dt.year, now_dt.month)[1]
        next_run = now_dt.replace(day=last_day, hour=23, minute=59)
        schedule(
            'publications.tasks.send_monthly_email',
            schedule_type='M', repeats=-1, next_run=next_run,
            kwargs={'trigger_source': 'scheduled', 'sent_by': sent_by.id if sent_by else None}
        )
        logger.info("Scheduled monthly email for %s", next_run)


def schedule_subscription_email_task(sent_by=None):
    if not Schedule.objects.filter(func='publications.tasks.send_subscription_based_email').exists():
        now_dt = datetime.now()
        last_day = calendar.monthrange(now_dt.year, now_dt.month)[1]
        next_run = now_dt.replace(day=last_day, hour=23, minute=59)
        schedule(
            'publications.tasks.send_subscription_based_email',
            schedule_type='M', repeats=-1, next_run=next_run,
            kwargs={'trigger_source': 'scheduled', 'sent_by': sent_by.id if sent_by else None}
        )
        logger.info("Scheduled subscription email for %s", next_run)


def regenerate_geojson_cache():
    cache_dir = os.path.join(tempfile.gettempdir(), "optimap_cache")
    os.makedirs(cache_dir, exist_ok=True)

    json_path = os.path.join(cache_dir, 'geojson_cache.json')
    with open(json_path, 'w') as f:
        serialize(
            'geojson',
            Publication.objects.filter(status='p'),
            geometry_field='geometry',
            srid=4326,
            stream=f
        )

    gzip_path = json_path + '.gz'
    with open(json_path, 'rb') as fin, gzip.open(gzip_path, 'wb') as fout:
        fout.writelines(fin)

    size = os.path.getsize(json_path)
    logger.info("Cached GeoJSON at %s (%d bytes), gzipped at %s", json_path, size, gzip_path)
    return json_path


def convert_geojson_to_geopackage(geojson_path):
    cache_dir = os.path.join(tempfile.gettempdir(), "optimap_cache")
    os.makedirs(cache_dir, exist_ok=True)
    gpkg = os.path.join(cache_dir, 'publications.gpkg')
    cmd = ["ogr2ogr", "-f", "GPKG", gpkg, geojson_path]
    try:
        subprocess.check_call(cmd)
        logger.info("Generated GeoPackage at %s", gpkg)
    except subprocess.CalledProcessError as e:
        logger.error("ogr2ogr failed: %s", e)
        return None
    return gpkg


def regenerate_geopackage_cache():
    json_path = regenerate_geojson_cache()
    gpkg_path = convert_geojson_to_geopackage(json_path)
    return json_path, gpkg_path