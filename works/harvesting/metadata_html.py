# SPDX-FileCopyrightText: 2026 OPTIMETA and KOMET projects <https://projects.tib.eu/komet>
# SPDX-License-Identifier: GPL-3.0-or-later

"""HTML metadata extraction — geometry and temporal coverage.

Used by every harvester that fetches a publisher landing page (OAI-PMH,
RSS, Crossref). The extraction priority order is documented in
``extract_geometry_from_html`` and tested in tests/test_htmlparser.py.
"""

import json
import logging
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from django.contrib.gis.geos import GEOSGeometry, Polygon

logger = logging.getLogger(__name__)


_GEOJSON_TYPES = {
    "Point",
    "MultiPoint",
    "LineString",
    "MultiLineString",
    "Polygon",
    "MultiPolygon",
    "GeometryCollection",
}


def _wrap_in_collection(geom: GEOSGeometry) -> GEOSGeometry:
    # MultiPoint/MultiLineString/MultiPolygon subclass GeometryCollection in
    # Django but are not OGC GeometryCollections — check the OGC type string
    # directly so we always end up with a real GEOMETRYCOLLECTION.
    if geom.geom_type == "GeometryCollection":
        return geom
    return GEOSGeometry(
        json.dumps(
            {
                "type": "GeometryCollection",
                "geometries": [json.loads(geom.geojson)],
            }
        )
    )


def _polygon_from_bbox(west, south, east, north) -> Polygon:
    coords = (
        (west, south),
        (east, south),
        (east, north),
        (west, north),
        (west, south),
    )
    poly = Polygon(coords)
    poly.srid = 4326
    return poly


def _geom_from_geojson_dict(geo: dict) -> GEOSGeometry | None:
    if not isinstance(geo, dict):
        return None
    if geo.get("type") in _GEOJSON_TYPES:
        try:
            return _wrap_in_collection(GEOSGeometry(json.dumps(geo)))
        except Exception:
            return None
    schema_type = geo.get("@type")
    if schema_type == "GeoShape" and isinstance(geo.get("box"), str):
        try:
            south, west, north, east = (float(x) for x in geo["box"].split())
            return _wrap_in_collection(_polygon_from_bbox(west, south, east, north))
        except Exception:
            return None
    if schema_type == "GeoCoordinates":
        try:
            lat = float(geo["latitude"])
            lon = float(geo["longitude"])
            # Reject coordinates outside WGS84 bounds — some BDJ articles embed
            # projected coordinates (e.g. UTM, millions of metres) alongside valid
            # decimal-degree coordinates in the same contentLocation block.
            if not (-90 <= lat <= 90) or not (-180 <= lon <= 180):
                return None
            return _wrap_in_collection(GEOSGeometry(f"POINT({lon} {lat})", srid=4326))
        except Exception:
            return None
    return None


def _walk_jsonld(node):
    """Yield every dict node inside a JSON-LD document (handles @graph and lists)."""
    if isinstance(node, dict):
        yield node
        for v in node.values():
            yield from _walk_jsonld(v)
    elif isinstance(node, list):
        for item in node:
            yield from _walk_jsonld(item)


def _extract_jsonld_content_location(soup: BeautifulSoup) -> GEOSGeometry | None:
    # Extraction logic mirrors geoextent/lib/content_providers/Pensoft.py
    # (_extract_coordinates / _extract_coordinates_from_location).
    # Pensoft/ARPHA journals embed study-site points via schema:contentLocation
    # (not spatialCoverage), so we collect *all* locations into one collection.
    geometries = []
    for tag in soup.find_all("script", attrs={"type": "application/ld+json"}):
        raw = tag.string or tag.get_text() or ""
        if not raw.strip():
            continue
        try:
            doc = json.loads(raw)
        except Exception:
            continue
        for node in _walk_jsonld(doc):
            cl = node.get("contentLocation")
            if not cl:
                continue
            candidates = cl if isinstance(cl, list) else [cl]
            for entry in candidates:
                if not isinstance(entry, dict):
                    continue
                # geo sub-property may be a single GeoCoordinates or a list of them
                # (BDJ uses a list); fall back to the entry itself for direct GeoCoordinates.
                geo_val = entry.get("geo")
                geo_list = geo_val if isinstance(geo_val, list) else ([geo_val] if geo_val is not None else [entry])
                for geo in geo_list:
                    geom = _geom_from_geojson_dict(geo)
                    if geom is not None:
                        for i in range(geom.num_geom):
                            geometries.append(json.loads(geom[i].geojson))
    if not geometries:
        return None
    try:
        coll = {"type": "GeometryCollection", "geometries": geometries}
        return GEOSGeometry(json.dumps(coll))
    except Exception:
        return None


def _extract_jsonld_spatial(soup: BeautifulSoup) -> GEOSGeometry | None:
    for tag in soup.find_all("script", attrs={"type": "application/ld+json"}):
        raw = tag.string or tag.get_text() or ""
        if not raw.strip():
            continue
        try:
            doc = json.loads(raw)
        except Exception:
            continue
        for node in _walk_jsonld(doc):
            sc = node.get("spatialCoverage")
            if not sc:
                continue
            candidates = sc if isinstance(sc, list) else [sc]
            for entry in candidates:
                if not isinstance(entry, dict):
                    continue
                geo = entry.get("geo", entry)
                geom = _geom_from_geojson_dict(geo)
                if geom is not None:
                    return geom
    return None


def _extract_geojson_link(soup: BeautifulSoup, base_url: str | None) -> GEOSGeometry | None:
    link = None
    for tag in soup.find_all("link"):
        if tag.get("type") != "application/geo+json":
            continue
        rel = tag.get("rel") or []
        if isinstance(rel, str):
            rel = [rel]
        if "alternate" in rel:
            link = tag
            break
    if link is None or not link.get("href"):
        return None
    href = link["href"]
    if base_url:
        href = urljoin(base_url, href)
    try:
        resp = requests.get(
            href,
            timeout=10,
            headers={"Accept": "application/geo+json, application/json"},
        )
        resp.raise_for_status()
        doc = resp.json()
    except Exception as err:
        logger.debug("geo+json link fetch failed for %s: %s", href, err)
        return None
    geometries = []
    if isinstance(doc, dict):
        if doc.get("type") == "FeatureCollection":
            for feat in doc.get("features") or []:
                g = feat.get("geometry") if isinstance(feat, dict) else None
                if g and g.get("type") in _GEOJSON_TYPES:
                    geometries.append(g)
        elif doc.get("type") == "Feature" and isinstance(doc.get("geometry"), dict):
            geometries.append(doc["geometry"])
        elif doc.get("type") in _GEOJSON_TYPES:
            geometries.append(doc)
    if not geometries:
        return None
    try:
        if len(geometries) == 1:
            return _wrap_in_collection(GEOSGeometry(json.dumps(geometries[0])))
        coll = {"type": "GeometryCollection", "geometries": geometries}
        return GEOSGeometry(json.dumps(coll))
    except Exception as err:
        logger.debug("geo+json parse failed for %s: %s", href, err)
        return None


def _extract_dc_spatial_coverage(soup: BeautifulSoup) -> GEOSGeometry | None:
    for tag in soup.find_all("meta"):
        if tag.get("name") != "DC.SpatialCoverage":
            continue
        try:
            payload = json.loads(tag["content"])
            if payload.get("type") == "FeatureCollection":
                geom_data = payload["features"][0]["geometry"]
            elif payload.get("type") == "Feature":
                geom_data = payload["geometry"]
            else:
                geom_data = payload
            coll = {"type": "GeometryCollection", "geometries": [geom_data]}
            return GEOSGeometry(json.dumps(coll))
        except Exception:
            continue
    return None


def _extract_dc_box(soup: BeautifulSoup) -> GEOSGeometry | None:
    for tag in soup.find_all("meta"):
        if tag.get("name") != "DC.box":
            continue
        try:
            parts = {}
            for chunk in tag.get("content", "").split(";"):
                if "=" not in chunk:
                    continue
                k, v = chunk.split("=", 1)
                parts[k.strip().lower()] = v.strip()
            projection = parts.get("projection", "").upper().replace(":", "")
            if projection and projection not in ("EPSG4326",):
                continue
            west = float(parts["westlimit"])
            south = float(parts["southlimit"])
            east = float(parts["eastlimit"])
            north = float(parts["northlimit"])
            return _wrap_in_collection(_polygon_from_bbox(west, south, east, north))
        except Exception:
            continue
    return None


def extract_geometry_from_html(soup: BeautifulSoup, base_url: str | None = None):
    """Try, in priority order: schema.org JSON-LD spatialCoverage; an
    `application/geo+json` alternate link; DC.SpatialCoverage GeoJSON; DC.box
    bounding box. Returns ``(GEOSGeometry, source_label)`` or ``(None, None)``.
    """
    geom = _extract_jsonld_spatial(soup)
    if geom is not None:
        return geom, "schema.org JSON-LD"
    geom = _extract_jsonld_content_location(soup)
    if geom is not None:
        return geom, "schema.org contentLocation"
    geom = _extract_geojson_link(soup, base_url)
    if geom is not None:
        return geom, "link rel=alternate geo+json"
    geom = _extract_dc_spatial_coverage(soup)
    if geom is not None:
        return geom, "DC.SpatialCoverage"
    geom = _extract_dc_box(soup)
    if geom is not None:
        return geom, "DC.box"
    return None, None


def _split_iso_interval(value: str):
    """Parse an ISO 8601 interval. Treats '..' or empty as open-ended."""
    if not value:
        return None, None
    value = value.strip()
    if "/" not in value:
        return value, value
    start_raw, end_raw = value.split("/", 1)
    start = start_raw.strip() or None
    end = end_raw.strip() or None
    if start in ("..",):
        start = None
    if end in ("..",):
        end = None
    return start, end


def _extract_jsonld_temporal(soup: BeautifulSoup):
    for tag in soup.find_all("script", attrs={"type": "application/ld+json"}):
        raw = tag.string or tag.get_text() or ""
        if not raw.strip():
            continue
        try:
            doc = json.loads(raw)
        except Exception:
            continue
        for node in _walk_jsonld(doc):
            tc = node.get("temporalCoverage")
            if tc is None:
                continue
            candidate = tc[0] if isinstance(tc, list) and tc else tc
            if not isinstance(candidate, str):
                continue
            return _split_iso_interval(candidate)
    return None


def _extract_dc_temporal(soup: BeautifulSoup):
    for tag in soup.find_all("meta"):
        if tag.get("name") in ("DC.temporal", "DC.PeriodOfTime"):
            return _split_iso_interval(tag.get("content", ""))
    return None


def extract_timeperiod_from_html(soup: BeautifulSoup):
    """Returns ``([start_or_None], [end_or_None])`` matching the ArrayField
    convention on ``Work.timeperiod_*``. JSON-LD ``temporalCoverage`` is
    preferred over ``DC.temporal`` / ``DC.PeriodOfTime``. Open intervals
    (``..``) and missing sides are both surfaced as ``None``.
    """
    parsed = _extract_jsonld_temporal(soup)
    if parsed is None:
        parsed = _extract_dc_temporal(soup)
    if parsed is None:
        return [None], [None]
    start, end = parsed
    return [start], [end]
