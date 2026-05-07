# SPDX-FileCopyrightText: 2026 OPTIMETA and KOMET projects <https://projects.tib.eu/komet>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Reverse-geocoding helper for ``Work`` placename / country lookup (issue #222).

For multi-point geometries (e.g. the Mountain Wetlands harvester emits one
``Point`` per study site) a single centroid-based geocode is misleading —
the centroid of "Berlin and Tokyo" lands somewhere in Russia. Instead, we
geocode each representative point and return the **lowest common ancestor**
in the address hierarchy. So:

- All points in Berlin → ``("Berlin, Berlin, Germany", "DE")``.
- One in Berlin, one in Munich → ``("Germany", "DE")`` (state diverges).
- One in Germany, one in France → ``(None, None)`` (country diverges).
- Single Polygon over Sulawesi → its representative point → that placename.

Wraps ``geopy.geocoders.Nominatim``. Per-point lookups go through a long-TTL
cache (``reverse_geocode:<lat>:<lon>``, 3-decimal quantisation, ~100 m, 30
days) so works clustered in the same area share entries and we incur few
Nominatim hits in steady state. Failures (network errors, no result) never
raise — they degrade gracefully and the caller decides whether to clear the
work's fields or preserve them.
"""

from __future__ import annotations

import logging
from typing import Tuple

from django.conf import settings
from django.core.cache import caches

logger = logging.getLogger(__name__)

# 30 days: country boundaries don't move and Nominatim asks us to cache.
_CACHE_TTL = 30 * 24 * 3600
# Per-process LocMem cache. First lookup per worker is a Nominatim call;
# subsequent same-coordinate (or close-by, ~100 m) lookups hit memory.
_CACHE_ALIAS = "memory"

# Nominatim's address keys, broadest → most specific. The LCA walks this
# list and stops at the first divergent (or missing) level. Continent is
# rarely returned by Nominatim — included for completeness.
_ADDRESS_HIERARCHY = (
    "continent",
    "country",
    "state",
    "region",
    "county",
    "city",
    "town",
    "village",
    "suburb",
    "neighbourhood",
)

# Sentinel distinguishing "cached as None" (no Nominatim result for this
# coordinate — e.g. middle of the ocean) from "key not in cache yet".
_MISS = object()


def _cache_key(lat: float, lon: float) -> str:
    """Quantise to ~100 m (3 decimals) so close-by centroids share an entry."""
    return f"reverse_geocode:{round(lat, 3)}:{round(lon, 3)}"


def _build_geocoder():
    """Lazily import + construct the Nominatim geocoder.

    Imported inside the function so the test suite can patch
    ``works.services.geocoding._reverse_geocode_lookup`` (or
    ``_build_geocoder``) without paying the ``geopy`` import cost or hitting
    the network on module load.
    """
    from geopy.geocoders import Nominatim

    user_agent = getattr(settings, "OPTIMAP_GEOCODER_USER_AGENT",
                         settings.OPTIMAP_USER_AGENT)
    return Nominatim(user_agent=user_agent, timeout=10)


def _reverse_geocode_lookup(lat: float, lon: float) -> dict | None:
    """Return ``{"address": {...}, "display_name": "..."}`` for the coordinate.

    The ``address`` dict is Nominatim's structured ``addressdetails`` payload
    (``country``, ``state``, ``city``, …) used by ``_common_address`` for the
    LCA computation. ``display_name`` is the formatted hierarchy used as the
    placename in the single-point case.

    Returns ``None`` when Nominatim has no result for the coordinate (cached
    so we don't keep retrying ocean centroids). On exceptions returns ``None``
    *without* caching, so the next save can retry.
    """
    cache = caches[_CACHE_ALIAS]
    key = _cache_key(lat, lon)
    cached = cache.get(key, _MISS)
    if cached is not _MISS:
        return cached

    try:
        geocoder = _build_geocoder()
        location = geocoder.reverse(
            (lat, lon),
            language="en",
            zoom=10,  # city-level — enough for placename, avoids tiny POIs
            addressdetails=True,
        )
    except Exception as err:  # network errors, timeouts, etc.
        logger.warning("reverse-geocode failed for (%s, %s): %s", lat, lon, err)
        return None  # don't cache transient failures

    if location is None:
        result: dict | None = None
    else:
        raw = getattr(location, "raw", {}) or {}
        address = raw.get("address", {}) or {}
        display_name = getattr(location, "address", None) or raw.get("display_name")
        # Capture the stable OSM identifiers — `osm_type` ("node"/"way"/
        # "relation") + `osm_id` form a permalink at openstreetmap.org and are
        # portable across Nominatim instances; `place_id` is convenient but
        # specific to one Nominatim DB.
        osm_type = raw.get("osm_type")
        osm_id = raw.get("osm_id")
        result = {
            "address": address,
            "display_name": display_name,
            "osm_type": osm_type,
            "osm_id": osm_id,
            "place_id": raw.get("place_id"),
            "osm_url": (
                f"https://www.openstreetmap.org/{osm_type}/{osm_id}"
                if osm_type and osm_id else None
            ),
        }

    cache.set(key, result, timeout=_CACHE_TTL)
    return result


def reverse_geocode(lat: float, lon: float) -> Tuple[str | None, str | None]:
    """Return ``(display_name, country_code)`` for a single coordinate.

    Thin wrapper over ``_reverse_geocode_lookup`` for callers that only need
    the placename + country of one point. For multi-point geometries use
    ``geocode_geometry`` instead so the result reflects the LCA across all
    representative points rather than a single centroid that may be in a
    different region than any actual sample.
    """
    info = _reverse_geocode_lookup(lat, lon)
    if not info:
        return (None, None)
    address = info.get("address") or {}
    country = address.get("country_code")
    if country:
        country = country.upper()
    return (info.get("display_name"), country)


def _representative_points(geom, max_points: int = 20) -> list[tuple[float, float]]:
    """Sample up to ``max_points`` representative ``(lat, lon)`` pairs.

    Each ``Point`` in the geometry is sampled individually (so multi-point
    GeometryCollections are geocoded per-site). Polygons / lines contribute
    the four corners of their bounding box plus an interior point — sampling
    only an interior point would mask cross-border coverage: a Polygon
    spanning Germany and Poland geocodes through its centroid (which lands
    in one country) and the LCA blindly reports that country, even though
    the polygon's corners clearly cross the border. Sampling the corners
    forces ``_common_address`` to detect the divergence and fall back to
    the shared ancestor (or to ``None``). Bounded so a 500-vertex polygon
    doesn't trigger 500 Nominatim requests.
    """
    points: list[tuple[float, float]] = []
    seen: set[tuple[float, float]] = set()

    def _add(lat: float, lon: float):
        # Quantise to the cache resolution (~100 m) so envelope corners that
        # round to the same grid cell as an interior point don't waste a
        # Nominatim hit on the same neighbourhood.
        key = (round(lat, 3), round(lon, 3))
        if key in seen:
            return
        seen.add(key)
        points.append((lat, lon))

    def _walk(g):
        if len(points) >= max_points:
            return
        gt = g.geom_type
        if gt == "Point":
            _add(g.y, g.x)
        elif gt in ("MultiPoint", "GeometryCollection",
                    "MultiPolygon", "MultiLineString"):
            for child in g:
                _walk(child)
                if len(points) >= max_points:
                    return
        else:
            # Polygon, LineString, LinearRing — sample the envelope corners
            # plus an interior point. See module docstring above.
            try:
                minx, miny, maxx, maxy = g.extent
            except Exception:  # pragma: no cover — defensive
                minx = miny = maxx = maxy = None
            if minx is not None:
                for lat, lon in (
                    (miny, minx), (miny, maxx),
                    (maxy, minx), (maxy, maxx),
                ):
                    if len(points) >= max_points:
                        return
                    _add(lat, lon)
            try:
                pt = g.point_on_surface
            except Exception:  # pragma: no cover — defensive
                pt = g.centroid
            if len(points) < max_points:
                _add(pt.y, pt.x)

    _walk(geom)
    return points[:max_points]


def _common_address(addresses: list[dict]) -> Tuple[str | None, str | None]:
    """Compute the lowest common ancestor of a list of Nominatim address dicts.

    Walks ``_ADDRESS_HIERARCHY`` from broad to specific; stops at the first
    level where the addresses disagree (or where any address is missing the
    level). Returns ``(placename, country_code)``:

    - ``country_code`` is the shared ISO alpha-2 (``None`` when ≥2 distinct
      values appear, or when no address has one).
    - ``placename`` is the shared levels joined most-specific-first
      (``"Berlin, Germany"``), or ``None`` when nothing above continent is
      shared.
    """
    if not addresses:
        return (None, None)

    country_codes = {
        a.get("country_code") for a in addresses if a.get("country_code")
    }
    if len(country_codes) == 1:
        country_code = next(iter(country_codes)).upper()
    else:
        country_code = None

    shared: list[str] = []
    for key in _ADDRESS_HIERARCHY:
        values = [a.get(key) for a in addresses]
        if all(v is None for v in values):
            # Level missing entirely (e.g. Nominatim rarely returns
            # ``continent``) — skip and keep checking deeper levels.
            continue
        first = values[0]
        if first and all(v == first for v in values):
            shared.append(first)
        else:
            # Real divergence: at least one address disagrees, OR some
            # have it and some don't — stop here so we don't claim a
            # deeper match by accident.
            break

    placename = ", ".join(reversed(shared)) if shared else None
    return (placename, country_code)


def collect_geocoding_matches(geom, max_points: int = 20) -> list[dict]:
    """Per-point Nominatim matches for ``geom`` (cache-aware).

    Returns one dict per representative point that returned an address, with
    the stable OSM identifiers and the coordinates we asked Nominatim about:

        {"lat": …, "lon": …, "osm_type": "relation", "osm_id": 51477,
         "place_id": 12345, "osm_url": "https://www.openstreetmap.org/relation/51477",
         "display_name": "Berlin, Germany"}

    Shares the per-process cache with ``geocode_geometry`` so calling both
    on the same geometry hits Nominatim only once per coordinate. Used by the
    ``Work`` pre-save signal to record provenance for the LCA result; for
    multi-point geometries the LCA itself doesn't have a single OSM ID, so
    the caller stores this list instead.
    """
    matches: list[dict] = []
    for lat, lon in _representative_points(geom, max_points=max_points):
        info = _reverse_geocode_lookup(lat, lon)
        if not info or not info.get("address"):
            continue
        matches.append({
            "lat": lat,
            "lon": lon,
            "osm_type": info.get("osm_type"),
            "osm_id": info.get("osm_id"),
            "place_id": info.get("place_id"),
            "osm_url": info.get("osm_url"),
            "display_name": info.get("display_name"),
        })
    return matches


def geocode_geometry(
    geom, max_points: int = 20
) -> Tuple[str | None, str | None, int]:
    """Reverse-geocode each representative point of ``geom`` and return the LCA.

    Returns ``(placename, country_code, n_geocoded)``:

    - ``placename`` / ``country_code`` are the LCA across all successfully
      geocoded points (see ``_common_address``).
    - ``n_geocoded`` is the count of points that returned an address.
      Callers use this to distinguish "real no shared region" (``> 0`` with
      ``placename=None``) from "every Nominatim call failed" (``== 0``) and
      avoid clobbering populated fields on a transient outage.

    For a single-point geometry, this returns the same placename /
    country_code as ``reverse_geocode`` at that point.
    """
    points = _representative_points(geom, max_points=max_points)
    addresses: list[dict] = []
    for lat, lon in points:
        info = _reverse_geocode_lookup(lat, lon)
        if info and info.get("address"):
            addresses.append(info["address"])
    placename, country_code = _common_address(addresses)
    return (placename, country_code, len(addresses))
