import logging
logger = logging.getLogger(__name__)

from django_q.models import Schedule
from publications.models import Publication
from bs4 import BeautifulSoup
import json
import xml.dom.minidom
from django.contrib.gis.geos import GEOSGeometry
import requests
from django.core.mail import send_mail
from django.conf import settings
from django.utils.timezone import now
from django.contrib.auth import get_user_model
User = get_user_model()
from .models import EmailLog
from datetime import datetime, timedelta
from django_q.tasks import schedule
from django_q.models import Schedule
import time  
import calendar
import subprocess
import gzip
import os

# ------------------------------
# Helper functions for harvesting
# ------------------------------

def extract_geometry_from_html(content):
    for tag in content.find_all("meta"):
        if tag.get("name", None) == "DC.SpatialCoverage":
            data = tag.get("content", None)
            try:
                geom = json.loads(data)
                geom_data = geom["features"][0]["geometry"]
                # Prepare geometry data as a GeometryCollection
                type_geom = {'type': 'GeometryCollection'}
                geom_content = {"geometries": [geom_data]}
                type_geom.update(geom_content)
                geom_data_string = json.dumps(type_geom)
                try:
                    geom_object = GEOSGeometry(geom_data_string)
                    logger.debug('Found geometry: %s', geom_object)
                    return geom_object
                except Exception as e:
                    logger.error("Cannot create geometry from string '%s': %s", geom_data_string, e)
            except ValueError as e:
                logger.error("Error loading JSON from %s: %s", tag.get("name"), e)

def extract_timeperiod_from_html(content):
    period = [None, None]
    for tag in content.find_all("meta"):
        if tag.get("name", None) in ['DC.temporal', 'DC.PeriodOfTime']:
            data = tag.get("content", None)
            period = data.split("/")
            logger.debug('Found time period: %s', period)
            break
    return [period[0]], [period[1]]

def parse_oai_xml_and_save_publications(content):
    DOMTree = xml.dom.minidom.parseString(content)
    collection = DOMTree.documentElement
    articles = collection.getElementsByTagName("dc:identifier")
    articles_count = len(articles)
    for i in range(articles_count):
        identifier = collection.getElementsByTagName("dc:identifier")
        identifier_value = identifier[i].firstChild.nodeValue
        logger.debug("Retrieving %s", identifier_value)
        
        if identifier_value.startswith('http'):
            try:
                with requests.get(identifier_value) as response:
                    soup = BeautifulSoup(response.content, 'html.parser')
                    geom_object = extract_geometry_from_html(soup)
                    period_start, period_end = extract_timeperiod_from_html(soup)
            except Exception as e:
                logger.error("Error retrieving/extracting geometry from URL %s: %s", identifier_value, e)
                logger.error("Continuing with the next article...")
                continue
        else:
            geom_object = None
            period_start = []
            period_end = []

        title = collection.getElementsByTagName("dc:title")
        title_value = title[0].firstChild.nodeValue if title else None
        abstract = collection.getElementsByTagName("dc:description")
        abstract_text = abstract[0].firstChild.nodeValue if abstract else None
        journal = collection.getElementsByTagName("dc:publisher")
        journal_value = journal[0].firstChild.nodeValue if journal else None
        date = collection.getElementsByTagName("dc:date")
        date_value = date[0].firstChild.nodeValue if date else None

        publication = Publication(
            title=title_value,
            abstract=abstract_text,
            publicationDate=date_value,
            url=identifier_value,
            source=journal_value,
            geometry=geom_object,
            timeperiod_startdate=period_start,
            timeperiod_enddate=period_end
        )
        publication.save()
        logger.info('Saved new publication for %s: %s', identifier_value, publication.get_absolute_url())

def harvest_oai_endpoint(url):
    try:
        with requests.Session() as s:
            response = s.get(url)
            parse_oai_xml_and_save_publications(response.content)
    except requests.exceptions.RequestException as e:
        logger.error("The requested URL is invalid or has connection issues: %s", url)

# ------------------------------
# Email and Scheduling Functions
# ------------------------------

def send_monthly_email(trigger_source='manual', sent_by=None):
    recipients = User.objects.filter(userprofile__notify_new_manuscripts=True).values_list('email', flat=True)
    last_month = now().replace(day=1) - timedelta(days=1)
    new_manuscripts = Publication.objects.filter(creationDate__month=last_month.month)

    if not recipients.exists() or not new_manuscripts.exists():
        return

    subject = "New Manuscripts This Month"
    content = "Here are the new manuscripts:\n" + "\n".join([pub.title for pub in new_manuscripts])

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
                recipient, subject, content, sent_by=sent_by, trigger_source=trigger_source, status="success"
            )
            time.sleep(getattr(settings, "EMAIL_SEND_DELAY", 2))
        except Exception as e:
            error_message = str(e)
            EmailLog.log_email(
                recipient, subject, content, sent_by=sent_by, trigger_source=trigger_source, status="failed", error_message=error_message
            )

def schedule_monthly_email_task(sent_by=None):
    if not Schedule.objects.filter(func='publications.tasks.send_monthly_email').exists():
        now_dt = datetime.now()
        last_day = calendar.monthrange(now_dt.year, now_dt.month)[1]
        next_run_date = now_dt.replace(day=last_day, hour=23, minute=59)
        schedule(
            'publications.tasks.send_monthly_email',
            schedule_type='M',
            repeats=-1,
            next_run=next_run_date,
            kwargs={'trigger_source': 'scheduled', 'sent_by': sent_by.id if sent_by else None}
        )

# ------------------------------
# New GeoJSON/GeoPackage Cache Functions
# ------------------------------

def regenerate_geojson_cache():
    """
    Serializes all Publication objects into a GeoJSON FeatureCollection,
    writes it to a file, and creates a gzipped version.
    """
    from django.core.serializers import serialize
    features = []
    geojson_str = serialize('geojson', Publication.objects.all(), geometry_field='geometry')
    try:
        geojson_obj = json.loads(geojson_str)
        features = geojson_obj.get("features", [])
    except Exception as e:
        logger.error("Error parsing GeoJSON: %s", e)
    
    full_collection = {
        "type": "FeatureCollection",
        "crs": {"type": "name", "properties": {"name": "EPSG:4326"}},
        "features": features
    }
    
    cache_dir = os.path.join(os.path.dirname(__file__), 'cache')
    os.makedirs(cache_dir, exist_ok=True)
    
    json_path = os.path.join(cache_dir, 'geojson_cache.json')
    with open(json_path, 'w') as f:
        json.dump(full_collection, f)
    
    gzip_path = os.path.join(cache_dir, 'geojson_cache.json.gz')
    with gzip.open(gzip_path, 'wt') as f:
        json.dump(full_collection, f)
    
    logger.info("GeoJSON cache regenerated successfully.")
    return json_path

def convert_geojson_to_geopackage(geojson_path):
    """
    Converts the GeoJSON file at geojson_path to a GeoPackage using ogr2ogr.
    """
    cache_dir = os.path.join(os.path.dirname(__file__), 'cache')
    geopackage_path = os.path.join(cache_dir, 'publications.gpkg')
    cmd = ["ogr2ogr", "-f", "GPKG", geopackage_path, geojson_path]
    try:
        subprocess.check_call(cmd)
        logger.info("GeoPackage generated at: %s", geopackage_path)
    except subprocess.CalledProcessError as e:
        logger.error("Error converting GeoJSON to GeoPackage: %s", e)
        geopackage_path = None
    return geopackage_path

def regenerate_geopackage_cache():
    """
    Regenerates the GeoJSON cache and converts it to a GeoPackage.
    Intended to be run on a schedule via Django Q.
    """
    json_path = regenerate_geojson_cache()
    gpkg_path = convert_geojson_to_geopackage(json_path)
    return gpkg_path
