# SPDX-FileCopyrightText: 2025 OPTIMETA and KOMET projects <https://projects.tib.eu/komet>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Views for region HTML landing pages (continents and oceans) with caching support."""

import logging

from django.conf import settings
from django.core.cache import cache
from django.core.paginator import EmptyPage, PageNotAnInteger, Paginator
from django.http import Http404
from django.shortcuts import render
from django.urls import reverse

from .feeds import get_region_from_slug
from .models import GlobalRegion
from .seo import build_feed_page_meta
from .utils.geojson import publications_to_geojson
from .utils.geometry import annotate_rounded_geometry

logger = logging.getLogger(__name__)


def _get_regional_publications(region):
    """Get published works linked to the region (offline point-in-polygon M2M).

    Reads the persisted ``Work.regions`` association (populated by the
    ``assign_work_regions`` signal and the ``backfill_work_regions`` sweep)
    rather than re-intersecting every published work's geometry on each request.
    """
    return list(
        annotate_rounded_geometry(
            region.works.filter(status="p").exclude(url__isnull=True).exclude(url__exact="").order_by("-creationDate")
        )
    )


def invalidate_region_page_cache(region):
    """Delete the cached landing-page context for a region.

    Called whenever ``Work.regions`` membership changes (the ``assign_work_regions``
    signal or the ``backfill_work_regions`` sweep) so the page reflects new
    associations before ``FEED_CACHE_HOURS`` elapses, instead of serving a stale
    (possibly empty) page for up to a day.
    """
    if region is None:
        return
    kind = "continent" if region.region_type == GlobalRegion.CONTINENT else "ocean"
    cache.delete(f"feed_page:{kind}:{region.get_slug()}")


def continent_feed_page(request, continent_slug):
    """Display HTML landing page for a continent region. Supports ?now to bypass cache."""
    force_refresh = request.GET.get("now") is not None

    region = get_region_from_slug(continent_slug)
    if region is None or region.region_type != GlobalRegion.CONTINENT:
        raise Http404(f"Continent not found: {continent_slug}")

    cache_key = f"feed_page:continent:{continent_slug}"

    if not force_refresh:
        cached_data = cache.get(cache_key)
        if cached_data:
            logger.debug("Serving cached continent page: %s", continent_slug)
            return render(request, "feed_page.html", _with_region_seo(request, cached_data, region))

    logger.debug("Generating fresh continent page: %s", continent_slug)
    publications = _get_regional_publications(region)

    context = {
        "region": region,
        "region_type": "Continent",
        "works": publications,
        "publications_geojson": publications_to_geojson(publications),
        "region_geojson": region.geom.geojson,
        "feed_urls": {
            "georss": reverse("optimap:api-continent-georss", kwargs={"continent_slug": continent_slug}),
            "atom": reverse("optimap:api-continent-atom", kwargs={"continent_slug": continent_slug}),
        },
    }

    cache_hours = getattr(settings, "FEED_CACHE_HOURS", 24)
    cache.set(cache_key, context, timeout=cache_hours * 3600)

    return render(request, "feed_page.html", _with_region_seo(request, context, region))


def ocean_feed_page(request, ocean_slug):
    """Display HTML landing page for an ocean region. Supports ?now to bypass cache."""
    force_refresh = request.GET.get("now") is not None

    region = get_region_from_slug(ocean_slug)
    if region is None or region.region_type != GlobalRegion.OCEAN:
        raise Http404(f"Ocean not found: {ocean_slug}")

    cache_key = f"feed_page:ocean:{ocean_slug}"

    if not force_refresh:
        cached_data = cache.get(cache_key)
        if cached_data:
            logger.debug("Serving cached ocean page: %s", ocean_slug)
            return render(request, "feed_page.html", _with_region_seo(request, cached_data, region))

    logger.debug("Generating fresh ocean page: %s", ocean_slug)
    publications = _get_regional_publications(region)

    context = {
        "region": region,
        "region_type": "Ocean",
        "works": publications,
        "publications_geojson": publications_to_geojson(publications),
        "region_geojson": region.geom.geojson,
        "feed_urls": {
            "georss": reverse("optimap:api-ocean-georss", kwargs={"ocean_slug": ocean_slug}),
            "atom": reverse("optimap:api-ocean-atom", kwargs={"ocean_slug": ocean_slug}),
        },
    }

    cache_hours = getattr(settings, "FEED_CACHE_HOURS", 24)
    cache.set(cache_key, context, timeout=cache_hours * 3600)

    return render(request, "feed_page.html", _with_region_seo(request, context, region))


def _with_region_seo(request, context: dict, region) -> dict:
    """Augment a (possibly cached) region-page context with per-request keys.

    SEO metadata, canonical URL, and pagination are all request-bound and kept
    out of the cache so the URL is correct for whatever host served the request.
    """
    bbox = None
    try:
        if region and region.geom:
            extent = region.geom.extent  # (xmin, ymin, xmax, ymax)
            bbox = (extent[0], extent[1], extent[2], extent[3])
    except Exception:
        bbox = None

    page_url = request.path
    meta = build_feed_page_meta(
        request,
        region_name=region.name if region else None,
        region_bbox=bbox,
        page_url=page_url,
    )
    augmented = dict(context)
    augmented["meta"] = meta
    augmented["canonical_url"] = request.build_absolute_uri(page_url)

    works = augmented.get("works", [])
    try:
        page_size = int(request.GET.get("size", settings.WORKS_PAGE_SIZE_DEFAULT))
        page_size = max(settings.WORKS_PAGE_SIZE_MIN, min(page_size, settings.WORKS_PAGE_SIZE_MAX))
    except (ValueError, TypeError):
        page_size = settings.WORKS_PAGE_SIZE_DEFAULT

    paginator = Paginator(works, page_size)
    try:
        page_obj = paginator.page(request.GET.get("page", 1))
    except PageNotAnInteger:
        page_obj = paginator.page(1)
    except EmptyPage:
        page_obj = paginator.page(paginator.num_pages)

    augmented["page_obj"] = page_obj
    augmented["page_size"] = page_size
    augmented["page_size_options"] = settings.WORKS_PAGE_SIZE_OPTIONS
    augmented["page_publications_geojson"] = publications_to_geojson(list(page_obj.object_list))

    return augmented
