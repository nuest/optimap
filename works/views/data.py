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

import logging
logger = logging.getLogger(__name__)

import os
from django.http import FileResponse, Http404
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
from works.models import Work

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
    layer = ds.CreateLayer("works", srs, ogr.wkbGeometryCollection)

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
