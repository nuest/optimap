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
from django.core.paginator import Paginator
from django.views.decorators.cache import never_cache
from django.conf import settings
from django.urls import reverse
from django.http import Http404
from works.models import Work
from works.utils.statistics import get_cached_statistics


def contribute(request):
    """
    Page showing harvested publications that need spatial or temporal extent contributions.
    Displays publications with Harvested status that are missing geometry or temporal extent.

    Supports pagination with user-selectable page size.
    """
    from django.contrib.gis.geos import GeometryCollection
    from django.db.models import Q
    from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger

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

    # Get publications that are harvested and missing spatial OR temporal extent
    publications_query = Work.objects.filter(
        status='h',  # Harvested status
    ).filter(
        Q(geometry__isnull=True) |  # NULL geometry
        Q(geometry__isempty=True) |  # Empty GeometryCollection
        Q(timeperiod_startdate__isnull=True) |  # NULL start date
        Q(timeperiod_enddate__isnull=True)      # NULL end date
    ).order_by('-creationDate')

    # Create paginator
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
    from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
    from works.utils.statistics import get_cached_statistics

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
    """
    from works.utils.identifiers import resolve_work_identifier

    is_admin = request.user.is_authenticated and request.user.is_staff

    # Resolve identifier to work object
    work, identifier_type = resolve_work_identifier(identifier)

    # Check access permissions
    if not is_admin and work.status != 'p':
        raise Http404("Work not found.")

    feature_json = None
    if work.geometry and not work.geometry.empty:
        feature = {
            "type": "Feature",
            "geometry": json.loads(work.geometry.geojson),
            "properties": {"title": work.title, "doi": work.doi or None},
        }
        feature_json = json.dumps(feature)

    # Check if geometry is missing (NULL or empty)
    has_geometry = work.geometry and not work.geometry.empty

    # Check if temporal extent is missing
    has_temporal = bool(work.timeperiod_startdate or work.timeperiod_enddate)

    # Users can contribute if work is harvested and missing either geometry or temporal extent
    can_contribute = request.user.is_authenticated and work.status == 'h' and (not has_geometry or not has_temporal)

    # Can publish if: Contributed status OR (Harvested with at least one extent type)
    can_publish = is_admin and (work.status == 'c' or (work.status == 'h' and (has_geometry or has_temporal)))
    can_unpublish = is_admin and work.status == 'p'  # Can unpublish published works

    # Get most recent successful Wikidata export
    latest_wikidata_export = work.wikidata_exports.filter(
        action__in=['created', 'updated']
    ).order_by('-export_date').first()

    # Get all Wikidata exports for admin view
    all_wikidata_exports = work.wikidata_exports.all() if is_admin else []

    # Determine if we should use ID-based URLs (when work has no DOI)
    use_id_urls = not work.doi

    context = {
        "work": work,
        "feature_json": feature_json,
        "timeperiod_label": _format_timeperiod(work),
        "authors_list": _normalize_authors(work),
        "is_admin": is_admin,
        "status_display": work.get_status_display() if is_admin else None,
        "has_geometry": has_geometry,
        "has_temporal": has_temporal,
        "can_contribute": can_contribute,
        "can_publish": can_publish,
        "can_unpublish": can_unpublish,
        "show_provenance": is_admin,
        "latest_wikidata_export": latest_wikidata_export,
        "all_wikidata_exports": all_wikidata_exports,
        "use_id_urls": use_id_urls,
        "identifier_type": identifier_type,  # Pass to template for debugging/analytics
    }
    return render(request, "work_landing_page.html", context)
