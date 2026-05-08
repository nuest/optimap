# SPDX-FileCopyrightText: 2025 OPTIMETA and KOMET projects <https://projects.tib.eu/komet>
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Work-specific views.

This module handles:
- Work landing pages
- Work lists
- Work contribution pages
"""

import logging
import json
import re
from urllib.parse import unquote

logger = logging.getLogger(__name__)

from django.shortcuts import render, get_object_or_404
from django.contrib.gis.geos import GeometryCollection
from django.core.cache import caches
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.db.models import Q
from django.utils.cache import add_never_cache_headers, patch_response_headers
from django.views.decorators.cache import never_cache
from django.conf import settings
from django.urls import reverse
from django.http import Http404, FileResponse
from django.views.decorators.http import require_GET
from works.models import Collection, Work
from works.seo import build_schema_org_for_work, build_work_meta, citation_meta_tags, coins_title, geo_meta_tags
from works.services.preview_image import (
    cache_path_for as _preview_cache_path,
    render_work_preview,
)
from works.utils.identifiers import resolve_work_identifier
from works.utils.statistics import get_cached_statistics


def contribute(request):
    """Page showing harvested works that need spatial or temporal extent.

    Optional ``?collection=<id|identifier|short_slug>`` narrows the listing
    to a single Collection (anonymous / non-staff users only see published
    collections; unknown values surface a warning).
    """
    page_size = request.GET.get('size', settings.WORKS_PAGE_SIZE_DEFAULT)
    try:
        page_size = int(page_size)
        page_size = max(settings.WORKS_PAGE_SIZE_MIN, min(page_size, settings.WORKS_PAGE_SIZE_MAX))
    except (ValueError, TypeError):
        page_size = settings.WORKS_PAGE_SIZE_DEFAULT

    page_number = request.GET.get('page', 1)

    publications_query = Work.objects.filter(
        status='h',
    ).filter(
        Q(geometry__isnull=True)
        | Q(geometry__isempty=True)
        | Q(timeperiod_startdate__isnull=True)
        | Q(timeperiod_enddate__isnull=True)
    ).order_by('-creationDate')

    filter_collection = None
    filter_raw = request.GET.get('collection', '').strip()
    filter_invalid = False
    if filter_raw:
        is_admin = request.user.is_authenticated and request.user.is_staff
        candidates = Collection.objects.all() if is_admin else Collection.objects.filter(is_published=True)
        match = None
        if filter_raw.isdigit():
            match = candidates.filter(pk=int(filter_raw)).first()
        if match is None:
            match = candidates.filter(identifier=filter_raw).first() or candidates.filter(short_slug=filter_raw).first()
        if match is not None:
            filter_collection = match
            publications_query = publications_query.filter(collections=match)
        else:
            filter_invalid = True

    paginator = Paginator(publications_query, page_size)
    try:
        page_obj = paginator.page(page_number)
    except PageNotAnInteger:
        page_obj = paginator.page(1)
    except EmptyPage:
        page_obj = paginator.page(paginator.num_pages)

    context = {
        'works': page_obj,
        'page_obj': page_obj,
        'page_size': page_size,
        'page_size_options': settings.WORKS_PAGE_SIZE_OPTIONS,
        'total_count': paginator.count,
        'filter_collection': filter_collection,
        'filter_raw': filter_raw,
        'filter_invalid': filter_invalid,
    }
    return render(request, 'contribute.html', context)

def _format_timeperiod(work):
    """
    Work stores timeperiod as arrays of strings.
    We show the first start/end if present, in a compact human form.
    """
    s_list = (work.timeperiod_startdate or [])
    e_list = (work.timeperiod_enddate   or [])
    s = s_list[0] if s_list else None
    e = e_list[0] if e_list else None

    if s and e:
        return f"{s} – {e}"
    if s:
        return f"from {s}"
    if e:
        return f"until {e}"
    return None

def _normalize_authors(work):
    """
    Try a few common attribute names. Accepts string (split on , or ;) or list/tuple.
    Returns list[str] or None.
    """
    candidates = (
        getattr(work, "authors", None),  # Primary: authors field
        getattr(work, "author", None),
        getattr(work, "creators", None),
        getattr(work, "creator", None),
    )
    raw = next((c for c in candidates if c), None)
    if not raw:
        return None
    if isinstance(raw, str):
        items = [x.strip() for x in re.split(r"[;,]", raw) if x.strip()]
        return items or None
    if isinstance(raw, (list, tuple)):
        items = [str(x).strip() for x in raw if str(x).strip()]
        return items or None
    return None

def works_list(request):
    """
    Public page that lists all works with pagination:
    - DOI present  -> /work/<doi> (site-local landing page)
    - no DOI       -> fall back to Work.url (external/original)

    Only published works (status='p') are shown to non-admin users.
    Admin users see all works with status labels.

    Supports pagination with user-selectable page size.
    """
    is_admin = request.user.is_authenticated and request.user.is_staff

    # Get page size from request or use default
    page_size = request.GET.get('size', settings.WORKS_PAGE_SIZE_DEFAULT)
    try:
        page_size = int(page_size)
        # Clamp page size within allowed limits
        page_size = max(settings.WORKS_PAGE_SIZE_MIN, min(page_size, settings.WORKS_PAGE_SIZE_MAX))
    except (ValueError, TypeError):
        page_size = settings.WORKS_PAGE_SIZE_DEFAULT

    # Get page number from request
    page_number = request.GET.get('page', 1)

    # Base queryset
    if is_admin:
        pubs = Work.objects.all().select_related('source')
    else:
        pubs = Work.objects.filter(status='p').select_related('source')

    pubs = pubs.order_by("-creationDate", "-id")

    # Create paginator
    paginator = Paginator(pubs, page_size)

    try:
        page_obj = paginator.page(page_number)
    except PageNotAnInteger:
        page_obj = paginator.page(1)
    except EmptyPage:
        page_obj = paginator.page(paginator.num_pages)

    # Build work data for current page
    works = []
    for work in page_obj:
        work_data = {
            "title": work.title,
            "doi": work.doi,
            "authors": work.authors or [],
            "source": work.source.name if work.source else None,
            "href": reverse("optimap:work-landing", args=[work.get_identifier()]),
        }

        # Add status info for admin users
        if is_admin:
            work_data["status"] = work.get_status_display()
            work_data["status_code"] = work.status

        works.append(work_data)

    # Get cached statistics
    stats = get_cached_statistics()

    # Build API URL for current page/size
    # DRF uses limit/offset pagination, so calculate offset from page number
    offset = (page_obj.number - 1) * page_size
    api_url = request.build_absolute_uri(
        '/api/v1/works/' +
        f'?limit={page_size}&offset={offset}'
    )

    context = {
        "works": works,
        "page_obj": page_obj,
        "page_size": page_size,
        "page_size_options": settings.WORKS_PAGE_SIZE_OPTIONS,
        "is_admin": is_admin,
        "statistics": stats,
        "api_url": api_url,
    }

    return render(request, "works.html", context)

_WORK_LANDING_CACHE_TIMEOUT = 24 * 3600


def _work_landing_cache_key(work, request) -> str:
    """Cache key for the anonymous landing-page context.

    Includes:
    - ``request.get_host()`` so dev (127.0.0.1) and prod entries don't pollute
      each other — the cached payload contains absolute URLs built from the
      request host.
    - ``work.lastUpdate`` (auto-bumped to ``now()`` on every ``Work.save()``)
      so any edit immediately misses the old entry. No explicit invalidation
      signal needed; superseded entries age out via TTL.
    """
    return (
        f"work_landing:ctx:{request.get_host()}:{work.id}:"
        f"{work.lastUpdate.timestamp() if work.lastUpdate else 0}"
    )


def _build_work_landing_cacheable(request, work, identifier_type):
    """Build the picklable, work-derived bits of the landing-page context.

    Excludes the ``Meta`` object (holds an unpicklable request reference)
    and the ``Work`` instance itself (re-fetched per request, cheap). The
    expensive ``schema.org`` JSON-LD dict is cached here; the view
    rebuilds the lightweight ``Meta`` object on each request and injects
    the cached schema via ``build_work_meta(request, work, kwargs_schema=...)``.
    """
    feature_json = None
    if work.geometry and not work.geometry.empty:
        feature = {
            "type": "Feature",
            "geometry": json.loads(work.geometry.geojson),
            "properties": {"title": work.title, "doi": work.doi or None},
        }
        feature_json = json.dumps(feature)

    return {
        "feature_json": feature_json,
        "timeperiod_label": _format_timeperiod(work),
        "authors_list": _normalize_authors(work),
        "has_geometry": bool(work.geometry and not work.geometry.empty),
        "has_temporal": bool(work.timeperiod_startdate or work.timeperiod_enddate),
        "use_id_urls": not work.doi,
        "identifier_type": identifier_type,
        "schema_org": build_schema_org_for_work(work, request),
        "citation_tags": citation_meta_tags(work, request),
        "geo_tags": geo_meta_tags(work),
        "coins_ctx": coins_title(work),
        "canonical_url": request.build_absolute_uri(
            reverse("optimap:work-landing", args=[work.get_identifier()])
        ),
    }


def work_landing(request, identifier):
    """
    Landing page for a work accessed by various identifier types.

    Tries to resolve the identifier in this order:
    1. DOI (if identifier contains '/' or starts with '10.')
    2. Internal database ID (if identifier is numeric)
    3. Handle (placeholder for future implementation)

    Embeds a small Leaflet map when geometry is available.

    Only published works (status='p') are accessible to non-admin users.
    Admin users can view all works with a status label.

    For anonymous requests the work-derived part of the context is cached
    in the in-memory backend (key ``work_landing:ctx:<host>:<work.id>``)
    and invalidated by ``works.signals.invalidate_work_caches`` on every
    ``Work`` save. Authenticated and staff requests always render live to
    keep status badges, publish buttons, and provenance current.
    """

    is_admin = request.user.is_authenticated and request.user.is_staff

    # Resolve identifier to work object.
    work, identifier_type = resolve_work_identifier(identifier)

    # Visibility: 'p' (Published) is fully public. 'h' (Harvested) and 'c'
    # (Contributed) are also visible to non-admins so the /contribute/ flow
    # can hand the user from the listing to the work landing page (where the
    # contribution form lives) — and so a successful contribution that flips
    # a work from 'h' to 'c' does not 404 the user on the post-reload. Drafts
    # ('d'), Testing ('t'), and Withdrawn ('w') remain admin-only.
    if not is_admin and work.status not in ('p', 'h', 'c'):
        raise Http404("Work not found.")

    is_anonymous = not request.user.is_authenticated
    cache_backend = caches['memory']
    cache_key = _work_landing_cache_key(work, request) if is_anonymous else None

    cacheable = None
    if cache_key:
        cacheable = cache_backend.get(cache_key)
    if cacheable is None:
        cacheable = _build_work_landing_cacheable(request, work, identifier_type)
        if cache_key:
            cache_backend.set(cache_key, cacheable, timeout=_WORK_LANDING_CACHE_TIMEOUT)

    # Rebuild Meta per request — cheap; the heavy schema dict comes from
    # the cache.
    meta = build_work_meta(request, work, kwargs_schema=cacheable["schema_org"])

    # User-dependent overlay — never cached.
    can_contribute = (
        request.user.is_authenticated
        and work.status == 'h'
        and (not cacheable["has_geometry"] or not cacheable["has_temporal"])
    )
    # Anonymous visitors who land on a contributable work via the /contribute/
    # listing get a "log in to contribute" call-to-action instead of a silent
    # "no form here" page.
    prompt_login_to_contribute = (
        not request.user.is_authenticated
        and work.status == 'h'
        and (not cacheable["has_geometry"] or not cacheable["has_temporal"])
    )
    can_publish = is_admin and (
        work.status == 'c'
        or (work.status == 'h' and (cacheable["has_geometry"] or cacheable["has_temporal"]))
    )
    can_unpublish = is_admin and work.status == 'p'

    latest_wikidata_export = work.wikidata_exports.filter(
        action__in=['created', 'updated']
    ).order_by('-export_date').first()
    all_wikidata_exports = work.wikidata_exports.all() if is_admin else []

    # Collections this work belongs to — hidden unpublished collections from
    # anonymous users so visibility rules match /collections/ and the
    # collection detail page. Computed per request (not cached) because
    # collection.is_published can flip without bumping Work.lastUpdate.
    visible_collections_qs = work.collections.all().order_by('name')
    if not is_admin:
        visible_collections_qs = visible_collections_qs.filter(is_published=True)
    visible_collections = list(visible_collections_qs)

    context = {
        **{k: v for k, v in cacheable.items() if k != "schema_org"},
        "work": work,
        "meta": meta,
        "is_admin": is_admin,
        "status_display": work.get_status_display() if is_admin else None,
        "can_contribute": can_contribute,
        "prompt_login_to_contribute": prompt_login_to_contribute,
        "can_publish": can_publish,
        "can_unpublish": can_unpublish,
        "show_provenance": is_admin,
        "latest_wikidata_export": latest_wikidata_export,
        "all_wikidata_exports": all_wikidata_exports,
        "visible_collections": visible_collections,
    }
    response = render(request, "work_landing_page.html", context)
    if is_anonymous:
        # Mirror the server-side TTL into ``Cache-Control: max-age=…`` and
        # ``Expires`` so browsers and intermediaries can co-cache. Saves
        # served from the cache key for ``Work.lastUpdate`` change as soon
        # as the work is edited, but downstream caches won't see that —
        # so they'll keep serving the stale entry until ``max-age`` expires.
        # 24h matches the server cache TTL.
        patch_response_headers(response, cache_timeout=_WORK_LANDING_CACHE_TIMEOUT)
    else:
        # Authenticated users see inline mutation controls (publish /
        # unpublish, contribute, add/remove from collection) whose state
        # must reflect the database after a POST. Without this, the
        # site-wide UpdateCacheMiddleware would cache the response keyed
        # by session cookie and the reloaded GET would short-circuit on
        # the stale entry until CACHE_MIDDLEWARE_SECONDS expired.
        add_never_cache_headers(response)
    return response


@require_GET
def work_preview_png(request, identifier):
    """og:image preview for work landing pages — issue #22.

    Returns a 1200×630 PNG of the work's spatial extent. Cached lazily on
    disk; invalidated by the post_save signal in ``works/signals.py``.
    Returns 404 when the work has no geometry — landings for those works
    don't emit an og:image so this endpoint should not be hit for them.
    """

    work, _ = resolve_work_identifier(identifier)
    # Same visibility rule as work_landing — preview is the og:image for the
    # landing page, so it has to be reachable wherever the landing page is.
    if not (request.user.is_authenticated and request.user.is_staff) and work.status not in ('p', 'h', 'c'):
        raise Http404("Work not found.")
    if not work.geometry or work.geometry.empty:
        raise Http404("Work has no geometry — no preview available.")

    cache_file = _preview_cache_path(work)
    if not cache_file.exists():
        try:
            data = render_work_preview(work)
        except Exception as err:
            logger.warning("preview render failed for work %s: %s", work.id, err)
            raise Http404("Preview unavailable.") from err
        cache_file.write_bytes(data)

    response = FileResponse(open(cache_file, "rb"), content_type="image/png")
    response["Cache-Control"] = "public, max-age=3600"
    return response
