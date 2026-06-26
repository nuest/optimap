# SPDX-FileCopyrightText: 2025 OPTIMETA and KOMET projects <https://projects.tib.eu/komet>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Views for region HTML landing pages (continents and oceans) with caching support."""

import json
import logging

from django.conf import settings
from django.contrib.admin.views.decorators import staff_member_required
from django.core.cache import cache
from django.core.paginator import EmptyPage, PageNotAnInteger, Paginator
from django.db.models import Q
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST
from django_q.humanhash import humanize as humanize_task_id
from django_q.tasks import async_task

from .feeds import get_region_from_slug
from .models import GlobalRegion, Work
from .seo import build_feed_page_meta
from .utils.geojson import publications_to_geojson
from .utils.geometry import annotate_rounded_geometry
from .utils.provenance import append_event, set_block

logger = logging.getLogger(__name__)

# A work whose ``provenance['regions']['source']`` is NOT the curator sentinel
# ``"manual"``. Written as an explicit ``isnull OR != manual`` because a plain
# ``.exclude(provenance__regions__source="manual")`` also drops rows where the
# JSON path is absent (SQL ``NOT NULL`` is NULL, i.e. not TRUE) — that would hide
# every yet-uncurated work. Reused by the backfill sweep in works.tasks.
NOT_MANUAL_REGION = Q(provenance__regions__source__isnull=True) | ~Q(provenance__regions__source="manual")


def unmatched_regions_qs():
    """Works with a geometry but no linked region, awaiting curation.

    The region mirror of ``works.views_indexed._unmatched_works_qs``: the same
    set the region backfill sweep processes, minus works a curator has already
    decided on manually. A manual decision (assign or "will not be matched")
    writes a ``provenance['regions']['source'] == 'manual'`` block, so excluding
    it keeps a curated work — including one excluded with **zero** regions —
    from reappearing in the list.
    """
    return (
        Work.objects.filter(geometry__isnull=False)
        .exclude(geometry__isempty=True)
        .filter(regions__isnull=True)
        .filter(NOT_MANUAL_REGION)
        .only("id", "title", "doi")  # the curation list renders only these
        .order_by("id")
    )


@staff_member_required
@require_POST
def set_work_region(request, work_id):
    """Manually assign one or more global regions to a work, or mark it "will not
    be matched".

    Staff-only. Body is JSON: ``{"region_ids": [5, 9]}`` to set several regions
    at once (multi-valued, since a work legitimately spans its continent and an
    ocean), the single-value ``{"region_id": 5}`` to *add* one region, or
    ``{"exclude": true}`` to mark the work as not applicable (e.g. a coastal
    point falling in the sliver gap between continent and ocean outlines).
    Records a detailed manual provenance block plus a ``region_curation`` audit
    event. The decision is preserved by ``works.signals.assign_work_regions``
    until the work's geometry changes, at which point automated matching resumes.
    """
    work = get_object_or_404(Work, pk=work_id)
    try:
        data = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"success": False, "error": "Invalid JSON body."}, status=400)

    now = timezone.now().isoformat()
    if data.get("exclude"):
        decision, method, region = "excluded", "curator_excluded", None
        work.regions.clear()  # "no region applies" — drop any auto-linked regions
    elif "region_ids" in data:
        # Multi-assign: replace the work's regions with exactly the chosen set.
        raw_ids = data.get("region_ids") or []
        if not isinstance(raw_ids, list):
            return JsonResponse({"success": False, "error": "region_ids must be a list."}, status=400)
        ids = [r for r in raw_ids if isinstance(r, int) or str(r).isdigit()]
        if len(ids) != len(raw_ids) or not ids:
            return JsonResponse({"success": False, "error": f"Invalid region ids {raw_ids!r}."}, status=400)
        regions = list(GlobalRegion.objects.filter(pk__in=ids))
        if len(regions) != len(set(ids)):
            return JsonResponse({"success": False, "error": f"Unknown region in {raw_ids!r}."}, status=400)
        decision, method, region = "assigned", "curator_assigned", None
        work.regions.set(regions)
    else:
        raw_id = data.get("region_id")
        region = (
            GlobalRegion.objects.filter(pk=raw_id).first()
            if isinstance(raw_id, int) or str(raw_id).isdigit()
            else None
        )
        if region is None:
            return JsonResponse({"success": False, "error": f"Unknown region {raw_id!r}."}, status=400)
        decision, method = "assigned", "curator_assigned"
        work.regions.add(region)  # additive single-region path

    region_name = region.name if region else None
    assigned = list(work.regions.all())  # read the resulting set once
    regions_block = [{"name": r.name, "region_type": r.get_region_type_display()} for r in assigned]
    region_names = [r.name for r in assigned]
    # append_event mutates provenance in-memory; set_block then persists the whole
    # dict via .update() without re-firing the save signals (and the M2M change
    # above does not fire post_save either).
    append_event(
        work,
        "region_curation",
        user_id=request.user.id,
        user_email=request.user.email,
        decision=decision,
        region=region_name,  # the single-region path keeps this for back-compat
        regions=region_names or None,
    )
    set_block(
        work,
        "regions",
        {
            "source": "manual",
            "method": method,
            "regions": regions_block,
            "decided_by": request.user.id,
            "decided_at": now,
        },
    )
    # Refresh every affected region's landing page (the work joined/left each one).
    for r in assigned:
        invalidate_region_page_cache(r)
    return JsonResponse({"success": True, "decision": decision, "region": region_name, "regions": region_names})


@staff_member_required
@require_POST
def trigger_region_backfill(request):
    """Enqueue a one-time background run of the region backfill task.

    Staff-only. The region mirror of ``trigger_country_backfill``: queues
    ``works.tasks.backfill_work_regions`` via Django-Q and returns the task id.
    """
    task_id = async_task("works.tasks.backfill_work_regions", trigger_source="manual")
    task_name = humanize_task_id(task_id)
    logger.info("User %s triggered region backfill (task %s)", request.user, task_name)
    return JsonResponse({"success": True, "task_id": task_id, "task_name": task_name})


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
