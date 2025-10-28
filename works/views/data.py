"""
Data export views.

This module handles:
- GeoJSON export
- GeoPackage export
- Data download endpoints
"""

import logging
logger = logging.getLogger(__name__)

import os
from django.http import FileResponse, Http404
from django.views.decorators.http import require_GET
import tempfile
from pathlib import Path
from works.tasks import regenerate_geojson_cache, regenerate_geopackage_cache
from osgeo import ogr, osr
from works.models import Work

ogr.UseExceptions()


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

@require_GET

def download_geopackage(request):
    """
    Returns the latest GeoPackage dump file.
    """
    gpkg_path = regenerate_geopackage_cache()
    if not gpkg_path or not os.path.exists(gpkg_path):
        raise Http404("GeoPackage not available.")
    return FileResponse(open(gpkg_path, 'rb'), as_attachment=True, filename=os.path.basename(gpkg_path))
