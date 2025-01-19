import logging
logger = logging.getLogger(__name__)

from django_q.models import Schedule
from publications.models import Publication, HarvestingEvent, Source
from bs4 import BeautifulSoup
import json
import xml.dom.minidom
from django.contrib.gis.geos import GEOSGeometry
import requests
from datetime import datetime


def extract_geometry_from_html(content):
    for tag in content.find_all("meta"):
        if tag.get("name", None) == "DC.SpatialCoverage":
            data = tag.get("content", None)
            try:
                geom = json.loads(data)
                geom_data = geom["features"][0]["geometry"]
                # preparing geometry data in accordance to geosAPI fields
                type_geom= {'type': 'GeometryCollection'}
                geom_content = {"geometries" : [geom_data]}
                type_geom.update(geom_content)
                geom_data_string= json.dumps(type_geom)
                try :
                    geom_object = GEOSGeometry(geom_data_string) # GeometryCollection object
                    logging.debug('Found geometry: %s', geom_object)
                    return geom_object
                except :
                    print("Invalid Geometry")
            except ValueError as e:
                print("Not a valid GeoJSON")

def extract_timeperiod_from_html(content):
    period = [None, None]
    for tag in content.find_all("meta"):
        if tag.get("name", None) in ['DC.temporal', 'DC.PeriodOfTime']:
            data = tag.get("content", None)
            period =  data.split("/")
            logging.debug('Found time period: %s', period)
            break;
    # returning arrays for array field in DB
    return [period[0]], [period[1]]

def parse_oai_xml_and_save_publications(content, event):
    
    DOMTree = xml.dom.minidom.parseString(content)
    collection = DOMTree.documentElement # pass DOMTree as argument
    articles = collection.getElementsByTagName("dc:identifier")

    for article in articles:
        identifier_value = article.firstChild.nodeValue if article.firstChild else None

        if Publication.objects.filter(url=identifier_value).exists():
            logger.info('Skipping duplicate publication: %s', identifier_value)
            continue  # Skip if publication already exists

        if identifier_value and identifier_value.startswith("http"):
            with requests.get(identifier_value) as response:
                soup = BeautifulSoup(response.content, "html.parser")
                geom_object = extract_geometry_from_html(soup)
                period_start, period_end = extract_timeperiod_from_html(soup)


        else:
            geom_object = None
            period_start = []
            period_end = []

        doi_value = collection.getElementsByTagName("dc:identifier")
        doi_text = doi_value[0].firstChild.nodeValue if doi_value else None

        if doi_text and Publication.objects.filter(doi__iexact=doi_text).exists():
            logger.info('Skipping duplicate publication (DOI): %s', doi_text)
            continue

        title = collection.getElementsByTagName("dc:title")
        title_value = title[0].firstChild.nodeValue if title else None
        abstract = collection.getElementsByTagName("dc:description")
        abstract_text = abstract[0].firstChild.nodeValue if abstract else None
        journal = collection.getElementsByTagName("dc:publisher")
        journal_value = journal[0].firstChild.nodeValue if journal else None
        date = collection.getElementsByTagName("dc:date")
        date_value = date[0].firstChild.nodeValue if date else None

        publication = Publication(
            title = title_value,
            abstract = abstract_text,
            publicationDate = date_value,
            url = identifier_value,
            journal = journal_value,
            geometry = geom_object,
            timeperiod_startdate = period_start,
            timeperiod_enddate = period_end)
        publication.save()
        logger.info('Saved new publication for %s: %s', identifier_value, publication)

def harvest_oai_endpoint(source_id):
    source = Source.objects.get(id=source_id)
    event = HarvestingEvent.objects.create(source=source, status="in_progress")
    try:
        with requests.Session() as session:
            response = session.get(source.url_field)
            response.raise_for_status()
            parse_oai_xml_and_save_publications(response.content, event)

            event.status = "completed"
            event.completed_at = datetime.now()
            event.save()
            print("Harvesting completed for %s", source.url_field)
    except requests.exceptions.RequestException as e:
        print("Error harvesting from %s: %s", source.url_field, e)
        event.status = "failed"
        event.log = str(e)
        event.save()

