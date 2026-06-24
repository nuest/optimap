# SPDX-FileCopyrightText: 2026 OPTIMETA and KOMET projects <https://projects.tib.eu/komet>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Public source landing page (``/in/<slug>/``).

Unifies the ``/in/<source>`` facet of issue #29 with the source landing page of
issue #253: a paginated list of a source's published works plus a coverage panel
fed by the weekly :class:`works.models.SourceCoverageSnapshot` (and the
OAI/Crossref/OpenAlex totals cached in ``Source.statistics``), and links to the
per-source GeoRSS/Atom feeds. List-only — no map. Mirrors
:func:`works.views_regions.continent_feed_page` for caching and pagination.
"""

import logging

from django.conf import settings
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, render
from django.urls import reverse

from .models import Source, Work
from .seo import build_facet_page_meta, coins_title
from .utils.geojson import build_works_map_context
from .utils.geometry import annotate_rounded_geometry
from .utils.pagination import paginate_works

logger = logging.getLogger(__name__)


def source_index(request):
    """`/in/` — directory of all sources with a landing page (#29, #253)."""
    sources = list(
        Source.objects.exclude(slug__isnull=True)
        .annotate(n=Count("works", filter=Q(works__status="p")))
        .order_by("-n", "name")
        .values("name", "slug", "n", "source_type")
    )
    page_url = reverse("optimap:in-index")
    meta = build_facet_page_meta(
        request,
        title="Sources — OPTIMAP",
        description="Browse all journals and sources harvested into OPTIMAP.",
        page_url=page_url,
    )
    return render(
        request,
        "source_index.html",
        {"sources": sources, "meta": meta, "canonical_url": request.build_absolute_uri(page_url)},
    )


def _coverage_context(source):
    """Build the coverage panel context from the latest snapshot + Source.statistics.

    Every value is optional: a source without an OpenAlex ID has no coverage_pct,
    a source with no snapshot yet has no rates, etc. The template renders each
    field conditionally so the page degrades gracefully.
    """
    snap = source.latest_coverage()
    stats = source.statistics or {}
    # Snapshot fields via the shared canonical mapping (same as the public API —
    # see SourceCoverageSnapshot.as_summary). Empty when no snapshot exists.
    summary = snap.as_summary() if snap is not None else {}
    coverage = dict(summary)
    coverage["snapshot"] = snap
    coverage["by_year"] = summary.get("by_year") or []
    # The snapshot's own OpenAlex total, kept under a distinct key so the
    # harvest-statistics total below can own ``openalex_total``.
    coverage["snapshot_openalex_total"] = summary.get("openalex_total")
    # Known totals from the harvest statistics (#253: "include all known totals").
    coverage["openalex_total"] = stats.get("openalex_works_count")
    coverage["oai_total"] = stats.get("oai_works_count")
    coverage["crossref_total"] = stats.get("crossref_works_count")
    return coverage


def source_page(request, source_slug):
    """Landing page for a single source: coverage panel + feeds + work list."""
    source = get_object_or_404(Source, slug=source_slug)

    works_qs = annotate_rounded_geometry(
        Work.objects.filter(status="p", source=source).select_related("source").order_by("-creationDate", "-id")
    )

    def _decorate(w):
        w.coins_ctx = coins_title(w)
        w.has_geo = bool(w.geometry and not w.geometry.empty)
        w.has_temporal = any(d is not None for d in (w.timeperiod_startdate or [])) or any(
            d is not None for d in (w.timeperiod_enddate or [])
        )

    page_obj, page_size = paginate_works(request, works_qs, decorate=_decorate)

    feed_urls = {
        "georss": reverse("optimap:api-source-georss", kwargs={"source_slug": source.slug}),
        "atom": reverse("optimap:api-source-atom", kwargs={"source_slug": source.slug}),
    }

    page_url = reverse("optimap:in-source", kwargs={"source_slug": source.slug})
    description = f"Published research works harvested from {source.name} on OPTIMAP."
    meta = build_facet_page_meta(
        request,
        title=f"{source.name} — works on OPTIMAP",
        description=description,
        page_url=page_url,
    )

    context = {
        "source": source,
        "page_obj": page_obj,
        "page_size": page_size,
        "page_size_options": settings.WORKS_PAGE_SIZE_OPTIONS,
        "work_count_total": page_obj.paginator.count,
        "coverage": _coverage_context(source),
        "feed_urls": feed_urls,
        "collection": source.collection if source.collection_id else None,
        "meta": meta,
        "canonical_url": request.build_absolute_uri(page_url),
        **build_works_map_context(
            page_obj.object_list,
            works_qs,
            page_url,
            all_cache_key=f"facet_map_all:source:{source.slug}",
            force_refresh=request.GET.get("now") is not None,
        ),
    }
    return render(request, "source_page.html", context)
