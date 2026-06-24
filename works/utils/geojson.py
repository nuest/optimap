# SPDX-FileCopyrightText: 2025 OPTIMETA and KOMET projects <https://projects.tib.eu/komet>
# SPDX-License-Identifier: GPL-3.0-or-later

import json

from django.conf import settings
from django.core.cache import cache

from works.utils.geometry import COORDINATE_PRECISION, round_geojson_coordinates

# W3C SDW-BP 15: include CRS and precision metadata in every FeatureCollection.
_GEOJSON_METADATA = {
    "crs": {"type": "name", "properties": {"name": "urn:ogc:def:crs:OGC:1.3:CRS84"}},
    "coordinate_precision": {
        "decimal_places": COORDINATE_PRECISION,
        "approximate_accuracy_m": 1.1,
        "note": "W3C SDW-BP 6 — coordinates are capped at 5 decimal places (~1.1 m at equator)",
    },
}


def publications_to_geojson(publications) -> str:
    """Serialize a list (or queryset) of Work objects to a GeoJSON FeatureCollection string."""
    features = []

    for work in publications:
        if not work.geometry or work.geometry.empty:
            continue

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

        features.append(
            {
                "type": "Feature",
                "geometry": json.loads(work._rounded_geojson)
                if getattr(work, "_rounded_geojson", None)
                else round_geojson_coordinates(json.loads(work.geometry.geojson)),
                "properties": {
                    "id": work.id,
                    "title": work.title,
                    "doi": work.doi,
                    "url": work.url,
                    "abstract": work.abstract,
                    "source": work.source.name if work.source else None,
                    "source_details": source_details,
                    "status": work.status,
                    "status_display": work.get_status_display(),
                    "publicationDate": work.publicationDate.isoformat() if work.publicationDate else None,
                    "timeperiod_startdate": work.timeperiod_startdate,
                    "timeperiod_enddate": work.timeperiod_enddate,
                    "authors": work.authors,
                    "keywords": work.keywords,
                    "topics": work.topics,
                    "openalex_id": work.openalex_id,
                    "openalex_match_info": work.openalex_match_info,
                    "openalex_fulltext_origin": work.openalex_fulltext_origin,
                    "openalex_is_retracted": work.openalex_is_retracted,
                    "openalex_ids": work.openalex_ids,
                    "openalex_open_access_status": work.openalex_open_access_status,
                },
            }
        )

    return json.dumps({"type": "FeatureCollection", **_GEOJSON_METADATA, "features": features})


def build_works_map_context(page_object_list, all_works, scope_key, *, all_cache_key=None, force_refresh=False):
    """Context for the shared works map (partials/works_map*.html).

    ``page_object_list`` is the current page's works (inline-rendered), ``all_works``
    is every work in the facet (for the "show all" toggle), and ``scope_key``
    namespaces the per-facet sessionStorage scope. Works without geometry are
    dropped by :func:`publications_to_geojson`; ``map_has_features`` says whether
    any survived, so the template can skip rendering an empty map.

    Serializing *all* works in a facet is the expensive part (a source can have
    thousands), so when ``all_cache_key`` is given the all-works GeoJSON + the
    has-features flag are cached for ``FEED_CACHE_HOURS`` (``?now`` →
    ``force_refresh=True`` bypasses, mirroring the region pages). The current
    page's GeoJSON is small and always computed fresh.
    """
    cached = None if force_refresh or not all_cache_key else cache.get(all_cache_key)
    if cached is None:
        all_list = list(all_works)
        all_geojson = publications_to_geojson(all_list)
        has_features = any(w.geometry is not None and not w.geometry.empty for w in all_list)
        if all_cache_key:
            timeout = getattr(settings, "FEED_CACHE_HOURS", 24) * 3600
            cache.set(all_cache_key, (all_geojson, has_features), timeout)
    else:
        all_geojson, has_features = cached
    return {
        "map_page_geojson": publications_to_geojson(list(page_object_list)),
        "map_all_geojson": all_geojson,
        "map_scope_key": scope_key,
        "map_has_features": has_features,
    }
