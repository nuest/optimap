# SPDX-FileCopyrightText: 2025 OPTIMETA and KOMET projects <https://projects.tib.eu/komet>
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Data export views.

This module handles:
- GeoJSON export
- GeoPackage export
- CSV export (with WKT geometry column, issue #206)
- Data download endpoints
"""

import json
import logging
logger = logging.getLogger(__name__)

import os
import subprocess
from django.conf import settings
from django.core.cache import cache
from django.core.serializers import serialize
from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_GET
import tempfile
from pathlib import Path
from drf_spectacular.utils import extend_schema, OpenApiResponse, inline_serializer
from drf_spectacular.types import OpenApiTypes
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework import serializers as drf_serializers

_DOWNLOAD_404 = OpenApiResponse(
    inline_serializer(
        name="DownloadNotFoundResponse",
        fields={"detail": drf_serializers.CharField()},
    ),
    description="Cached dump is missing and could not be regenerated.",
)
from works.tasks import (
    regenerate_geojson_cache,
    regenerate_geopackage_cache,
    regenerate_csv_cache,
)
from osgeo import ogr, osr
from works.models import Work, Collection

ogr.UseExceptions()


@extend_schema(
    summary="Download all published works as GeoJSON",
    description=(
        "Streams the cached GeoJSON `FeatureCollection` of every published work. "
        "When the client sends `Accept-Encoding: gzip` the response is gzipped on the "
        "wire (`Content-Encoding: gzip`); the payload itself remains GeoJSON. "
        "The cache is regenerated every 6 hours by a Django-Q schedule; this endpoint "
        "regenerates on demand if the cache is missing."
    ),
    tags=["Downloads"],
    responses={(200, 'application/json'): OpenApiTypes.BINARY},
)
@api_view(["GET"])
@permission_classes([AllowAny])
def download_geojson(request):
    """
    Returns the latest GeoJSON dump file, gzipped if the client accepts it,
    but always with Content-Type: application/json.
    """
    cache_dir = Path(tempfile.gettempdir()) / "optimap_cache"
    cache_dir.mkdir(exist_ok=True)
    json_path = regenerate_geojson_cache()
    gzip_path = Path(str(json_path) + ".gz")
    accept_enc = request.META.get('HTTP_ACCEPT_ENCODING', '')

    if 'gzip' in accept_enc and gzip_path.exists():
        response = FileResponse(
            open(gzip_path, 'rb'),
            content_type="application/json",
            as_attachment=True,
            filename=gzip_path.name
        )
        response['Content-Encoding'] = 'gzip'
        response['Content-Disposition'] = f'attachment; filename="{gzip_path.name}"'
    else:
        # Serve the plain JSON
        response = FileResponse(
            open(json_path, 'rb'),
            content_type="application/json",
            as_attachment=True,
            filename=Path(json_path).name
        )
        response['Content-Disposition'] = f'attachment; filename="{Path(json_path).name}"'
    return response

def _unwrap_ogr_geometry(geom):
    """OGR-API mirror of _unwrap_geometry_collection for the global GeoPackage builder."""
    if geom is None:
        return None
    if geom.GetGeometryType() != ogr.wkbGeometryCollection:
        return geom
    count = geom.GetGeometryCount()
    if count == 0:
        return None
    if count == 1:
        return geom.GetGeometryRef(0).Clone()
    types = {geom.GetGeometryRef(i).GetGeometryType() for i in range(count)}
    if len(types) == 1:
        base = types.pop()
        multi_map = {
            ogr.wkbPoint: ogr.wkbMultiPoint,
            ogr.wkbLineString: ogr.wkbMultiLineString,
            ogr.wkbPolygon: ogr.wkbMultiPolygon,
        }
        if base in multi_map:
            multi = ogr.Geometry(multi_map[base])
            for i in range(count):
                multi.AddGeometry(geom.GetGeometryRef(i).Clone())
            srs = geom.GetSpatialReference()
            if srs:
                multi.AssignSpatialReference(srs)
            return multi
    return geom


def generate_geopackage():
    cache_dir = os.path.join(tempfile.gettempdir(), "optimap_cache")
    os.makedirs(cache_dir, exist_ok=True)
    gpkg_path = os.path.join(cache_dir, "publications.gpkg")

    driver = ogr.GetDriverByName("GPKG")
    if os.path.exists(gpkg_path):
        driver.DeleteDataSource(gpkg_path)
    ds = driver.CreateDataSource(gpkg_path)
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(4326)
    # wkbUnknown allows mixed primitive types so QGIS can render features.
    layer = ds.CreateLayer("works", srs, ogr.wkbUnknown)

    for name in ("title", "abstract", "doi", "source"):
        field_defn = ogr.FieldDefn(name, ogr.OFTString)
        field_defn.SetWidth(255)
        layer.CreateField(field_defn)

    layer_defn = layer.GetLayerDefn()
    for work in Work.objects.all():
        feat = ogr.Feature(layer_defn)
        feat.SetField("title", work.title or "")
        feat.SetField("abstract", work.abstract or "")
        feat.SetField("doi", work.doi or "")
        feat.SetField("source", work.source.name if work.source else "")
        if work.geometry:
            wkb = work.geometry.wkb
            geom = ogr.CreateGeometryFromWkb(wkb)
            geom.AssignSpatialReference(srs)
            geom = _unwrap_ogr_geometry(geom)
            if geom is not None:
                feat.SetGeometry(geom)
        layer.CreateFeature(feat)
        feat = None

    ds = None
    return gpkg_path

@extend_schema(
    summary="Download all published works as a GeoPackage (.gpkg)",
    description=(
        "Returns the cached OGC GeoPackage of every published work — single layer "
        "`works`, EPSG:4326. Regenerated every 6 hours by a Django-Q schedule."
    ),
    tags=["Downloads"],
    responses={
        (200, 'application/geopackage+sqlite3'): OpenApiTypes.BINARY,
        404: _DOWNLOAD_404,
    },
)
@api_view(["GET"])
@permission_classes([AllowAny])
def download_geopackage(request):
    """
    Returns the latest GeoPackage dump file.
    """
    gpkg_path = regenerate_geopackage_cache()
    if not gpkg_path or not os.path.exists(gpkg_path):
        raise Http404("GeoPackage not available.")
    return FileResponse(open(gpkg_path, 'rb'), as_attachment=True, filename=os.path.basename(gpkg_path))


@extend_schema(
    summary="Download all published works as CSV (WKT geometry column)",
    description=(
        "Returns the cached CSV dump of every published work, with geometries serialized "
        "as a WKT column (issue #206). UTF-8, RFC 4180."
    ),
    tags=["Downloads"],
    responses={
        (200, 'text/csv'): OpenApiTypes.BINARY,
        404: _DOWNLOAD_404,
    },
)
@api_view(["GET"])
@permission_classes([AllowAny])
def download_csv(request):
    """
    Returns the latest CSV dump file (WKT geometry column, issue #206).
    """
    csv_path = regenerate_csv_cache()
    if not csv_path or not os.path.exists(csv_path):
        raise Http404("CSV not available.")
    return FileResponse(
        open(csv_path, 'rb'),
        content_type="text/csv; charset=utf-8",
        as_attachment=True,
        filename=os.path.basename(csv_path),
    )


# ---------------------------------------------------------------------------
# Per-collection download endpoints (#217)
# ---------------------------------------------------------------------------

_COLLECTION_404 = OpenApiResponse(
    inline_serializer(
        name="CollectionNotFoundResponse",
        fields={"detail": drf_serializers.CharField()},
    ),
    description="Collection not found or not published.",
)


def _collection_qs(collection):
    return Work.objects.filter(collections=collection, status="p")


def _unwrap_geometry_collection(geom):
    """Unwrap the GeometryCollection envelope that Django's GeometryCollectionField always emits.

    Django stores every geometry as a GeometryCollection, even when a work has a
    single Point or Polygon.  Leaving the wrapper intact causes ogr2ogr to declare
    the GeoPackage layer type as GEOMETRYCOLLECTION, which QGIS and most GIS tools
    cannot render with a default symbology (the layer loads but shows no features).

    Transformation rules applied to each GeoJSON geometry dict:
    - GeometryCollection([X])           → X          (unwrap single-member)
    - GeometryCollection([X, X, ...])   → Multi* X   (same-type members → Multi*)
    - GeometryCollection([X, Y, ...])   → unchanged  (mixed types, rare)
    - null / non-collection             → unchanged
    """
    if geom is None or geom.get("type") != "GeometryCollection":
        return geom
    parts = [g for g in (geom.get("geometries") or []) if g is not None]
    if not parts:
        return None
    if len(parts) == 1:
        return parts[0]
    types = {g["type"] for g in parts}
    if len(types) == 1:
        base = types.pop()
        multi_map = {"Point": "MultiPoint", "LineString": "MultiLineString", "Polygon": "MultiPolygon"}
        if base in multi_map:
            return {"type": multi_map[base], "coordinates": [g["coordinates"] for g in parts]}
    return geom


def _serialize_collection_geojson(collection):
    """Return a GeoJSON FeatureCollection string for published works in *collection*,
    with GeometryCollection wrappers unwrapped to primitive / Multi* types."""
    raw = serialize("geojson", _collection_qs(collection), geometry_field="geometry", srid=4326)
    data = json.loads(raw)
    for feat in data.get("features", []):
        feat["geometry"] = _unwrap_geometry_collection(feat.get("geometry"))
    return json.dumps(data)


def _generate_collection_converted_bytes(collection, ogr_fmt, layer_creation_options=None):
    """Serialize collection works to a GeoJSON (with unwrapped geometries) then convert via ogr2ogr."""
    with tempfile.TemporaryDirectory() as tmpdir:
        ext = ogr_fmt.lower() if ogr_fmt != "CSV" else "csv"
        geojson_path = os.path.join(tmpdir, "data.geojson")
        out_path = os.path.join(tmpdir, f"data.{ext}")
        with open(geojson_path, "w") as f:
            f.write(_serialize_collection_geojson(collection))
        cmd = ["ogr2ogr", "-f", ogr_fmt, out_path, geojson_path]
        for opt in layer_creation_options or []:
            cmd.extend(["-lco", opt])
        try:
            subprocess.check_output(cmd, stderr=subprocess.STDOUT, text=True)
        except subprocess.CalledProcessError as err:
            logger.warning("ogr2ogr %s failed for collection %s: %s",
                           ogr_fmt, collection.identifier, err.output)
            return None
        with open(out_path, "rb") as f:
            return f.read()


@extend_schema(
    summary="Download collection works as GeoJSON",
    description=(
        "Returns a GeoJSON FeatureCollection of all published works in the collection. "
        "Cached for `FEED_CACHE_HOURS` (default 24 h); pass `?now` to force refresh."
    ),
    tags=["Collections"],
    responses={
        (200, "application/json"): OpenApiTypes.BINARY,
        404: _COLLECTION_404,
    },
)
@api_view(["GET"])
@permission_classes([AllowAny])
def download_collection_geojson(request, collection_slug):
    collection = get_object_or_404(Collection, identifier=collection_slug, is_published=True)
    cache_key = f"download:collection:{collection_slug}:geojson"
    force = request.GET.get("now") is not None
    data = None if force else cache.get(cache_key)
    if data is None:
        data = _serialize_collection_geojson(collection)
        cache.set(cache_key, data, settings.FEED_CACHE_HOURS * 3600)
    response = HttpResponse(data, content_type="application/json")
    response["Content-Disposition"] = f'attachment; filename="optimap_collection_{collection_slug}.geojson"'
    return response


@extend_schema(
    summary="Download collection works as GeoPackage",
    description=(
        "Returns an OGC GeoPackage of all published works in the collection — single "
        "layer `OGRGeoJSON`, EPSG:4326. Cached for `FEED_CACHE_HOURS` (default 24 h); "
        "pass `?now` to force refresh."
    ),
    tags=["Collections"],
    responses={
        (200, "application/geopackage+sqlite3"): OpenApiTypes.BINARY,
        404: _COLLECTION_404,
    },
)
@api_view(["GET"])
@permission_classes([AllowAny])
def download_collection_gpkg(request, collection_slug):
    collection = get_object_or_404(Collection, identifier=collection_slug, is_published=True)
    cache_key = f"download:collection:{collection_slug}:gpkg"
    force = request.GET.get("now") is not None
    data = None if force else cache.get(cache_key)
    if data is None:
        data = _generate_collection_converted_bytes(collection, "GPKG")
        if data is None:
            raise Http404("GeoPackage generation failed.")
        cache.set(cache_key, data, settings.FEED_CACHE_HOURS * 3600)
    response = HttpResponse(data, content_type="application/geopackage+sqlite3")
    response["Content-Disposition"] = f'attachment; filename="optimap_collection_{collection_slug}.gpkg"'
    return response


@extend_schema(
    summary="Download collection works as CSV",
    description=(
        "Returns a CSV of all published works in the collection with geometries as a "
        "WKT column. UTF-8, RFC 4180. Cached for `FEED_CACHE_HOURS` (default 24 h); "
        "pass `?now` to force refresh."
    ),
    tags=["Collections"],
    responses={
        (200, "text/csv"): OpenApiTypes.BINARY,
        404: _COLLECTION_404,
    },
)
@api_view(["GET"])
@permission_classes([AllowAny])
def download_collection_csv(request, collection_slug):
    collection = get_object_or_404(Collection, identifier=collection_slug, is_published=True)
    cache_key = f"download:collection:{collection_slug}:csv"
    force = request.GET.get("now") is not None
    data = None if force else cache.get(cache_key)
    if data is None:
        data = _generate_collection_converted_bytes(collection, "CSV", ["GEOMETRY=AS_WKT"])
        if data is None:
            raise Http404("CSV generation failed.")
        cache.set(cache_key, data, settings.FEED_CACHE_HOURS * 3600)
    response = HttpResponse(data, content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="optimap_collection_{collection_slug}.csv"'
    return response
