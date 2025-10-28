"""
Views for feed HTML pages with caching support.
"""

import logging
import json
from django.shortcuts import render
from django.http import Http404
from django.core.cache import cache
from django.conf import settings
from django.core.serializers import serialize
from django.urls import reverse
from .models import Work, GlobalRegion
from .feeds import get_region_from_slug

logger = logging.getLogger(__name__)


def _publications_to_geojson(publications):
    """
    Convert publications queryset to GeoJSON format for map display.

    Args:
        publications: Queryset or list of Work objects

    Returns:
        str: GeoJSON string representation
    """
    features = []

    for work in publications:
        if not work.geometry or work.geometry.empty:
            continue

        # Prepare source details
        source_details = None
        if work.source:
            source_details = {
                "name": work.source.name,
                "display_name": work.source.name,
                "abbreviated_title": work.source.abbreviated_title,
                "homepage_url": work.source.homepage_url,
                "issn_l": work.source.issn_l,
                "publisher_name": work.source.publisher_name,
                "is_oa": work.source.is_oa,
                "is_preprint": work.source.is_preprint,
                "cited_by_count": work.source.cited_by_count,
                "works_count": work.source.works_count,
            }

        # Create GeoJSON feature
        feature = {
            "type": "Feature",
            "geometry": json.loads(work.geometry.geojson),
            "properties": {
                "id": work.id,
                "title": work.title,
                "doi": work.doi,
                "url": work.url,
                "abstract": work.abstract,
                "source": work.source.name if work.source else None,
                "source_details": source_details,
                "publicationDate": work.publicationDate.isoformat() if work.publicationDate else None,
                "timeperiod_startdate": work.timeperiod_startdate,
                "timeperiod_enddate": work.timeperiod_enddate,
                # Metadata fields
                "authors": work.authors,
                "keywords": work.keywords,
                "topics": work.topics,
                # OpenAlex-specific properties
                "openalex_id": work.openalex_id,
                "openalex_match_info": work.openalex_match_info,
                "openalex_fulltext_origin": work.openalex_fulltext_origin,
                "openalex_is_retracted": work.openalex_is_retracted,
                "openalex_ids": work.openalex_ids,
                "openalex_open_access_status": work.openalex_open_access_status,
            }
        }
        features.append(feature)

    geojson = {
        "type": "FeatureCollection",
        "features": features
    }

    return json.dumps(geojson)


def _get_regional_publications(region):
    """Get publications filtered by region."""
    # Use bbox overlap first for performance
    candidates = Work.objects.filter(
        status="p",
        geometry__isnull=False,
        geometry__bboverlaps=region.geom,
    ).exclude(
        url__isnull=True
    ).exclude(
        url__exact=""
    ).order_by("-creationDate")

    # Prepare geometry for faster intersection checks
    prepared_geom = region.geom.prepared

    # Filter by actual intersection and limit
    return [
        work for work in candidates
        if prepared_geom.intersects(work.geometry)
    ][:settings.FEED_MAX_ITEMS]


def continent_feed_page(request, continent_slug):
    """
    Display HTML page for continent feed.

    Supports ?now parameter to force cache refresh.
    """
    # Normalize slug
    force_refresh = request.GET.get('now') is not None

    # Get region
    region = get_region_from_slug(continent_slug)
    if region is None or region.region_type != GlobalRegion.CONTINENT:
        raise Http404(f"Continent not found: {continent_slug}")

    # Check cache
    cache_key = f"feed_page:continent:{continent_slug}"

    if not force_refresh:
        cached_data = cache.get(cache_key)
        if cached_data:
            logger.debug("Serving cached continent page: %s", continent_slug)
            return render(request, 'feed_page.html', cached_data)

    # Generate fresh data
    logger.debug("Generating fresh continent page: %s", continent_slug)
    publications = _get_regional_publications(region)

    context = {
        'region': region,
        'region_type': 'Continent',
        'works': publications,
        'publications_geojson': _publications_to_geojson(publications),
        'feed_urls': {
            'georss': reverse('optimap:api-continent-georss', kwargs={'continent_slug': continent_slug}),
            'atom': reverse('optimap:api-continent-atom', kwargs={'continent_slug': continent_slug}),
        }
    }

    # Cache for configured hours
    cache_hours = getattr(settings, 'FEED_CACHE_HOURS', 24)
    cache.set(cache_key, context, timeout=cache_hours * 3600)

    return render(request, 'feed_page.html', context)


def ocean_feed_page(request, ocean_slug):
    """
    Display HTML page for ocean feed.

    Supports ?now parameter to force cache refresh.
    """
    # Normalize slug
    force_refresh = request.GET.get('now') is not None

    # Get region
    region = get_region_from_slug(ocean_slug)
    if region is None or region.region_type != GlobalRegion.OCEAN:
        raise Http404(f"Ocean not found: {ocean_slug}")

    # Check cache
    cache_key = f"feed_page:ocean:{ocean_slug}"

    if not force_refresh:
        cached_data = cache.get(cache_key)
        if cached_data:
            logger.debug("Serving cached ocean page: %s", ocean_slug)
            return render(request, 'feed_page.html', cached_data)

    # Generate fresh data
    logger.debug("Generating fresh ocean page: %s", ocean_slug)
    publications = _get_regional_publications(region)

    context = {
        'region': region,
        'region_type': 'Ocean',
        'works': publications,
        'publications_geojson': _publications_to_geojson(publications),
        'feed_urls': {
            'georss': reverse('optimap:api-ocean-georss', kwargs={'ocean_slug': ocean_slug}),
            'atom': reverse('optimap:api-ocean-atom', kwargs={'ocean_slug': ocean_slug}),
        }
    }

    # Cache for configured hours
    cache_hours = getattr(settings, 'FEED_CACHE_HOURS', 24)
    cache.set(cache_key, context, timeout=cache_hours * 3600)

    return render(request, 'feed_page.html', context)
