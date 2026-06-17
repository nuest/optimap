# SPDX-FileCopyrightText: 2025 OPTIMETA and KOMET projects <https://projects.tib.eu/komet>
# SPDX-License-Identifier: GPL-3.0-or-later

from django.contrib.gis.db.models.functions import AsGeoJSON

# W3C SDW-BP 6: cap coordinate precision so we don't imply sub-meter accuracy
# that the underlying metadata doesn't support.  5 decimal places ≈ 1.1 m at
# the equator — sufficient for publication-level spatial coverage.
COORDINATE_PRECISION = 5


def round_geojson_coordinates(obj, precision=COORDINATE_PRECISION):
    """Recursively round every float in a parsed GeoJSON dict/list.

    Kept as a fallback for geometries not sourced from a queryset annotated
    via ``annotate_rounded_geometry`` (e.g. ad hoc model instances in tests);
    real call sites should prefer the DB-side annotation, which is an order
    of magnitude faster since PostGIS rounds during serialization instead of
    Python re-parsing/rounding/re-dumping the full-precision GeoJSON.
    """
    if isinstance(obj, list):
        return [round_geojson_coordinates(v, precision) for v in obj]
    if isinstance(obj, float):
        return round(obj, precision)
    if isinstance(obj, dict):
        return {k: round_geojson_coordinates(v, precision) for k, v in obj.items()}
    return obj


def annotate_rounded_geometry(
    queryset, geo_field="geometry", precision=COORDINATE_PRECISION, out_field="_rounded_geojson"
):
    """Annotate *queryset* with a PostGIS-rounded GeoJSON string for *geo_field*.

    Uses ``ST_AsGeoJSON(geom, precision)`` (via Django's ``AsGeoJSON``) so the
    rounding happens in the database in the same pass that produces the
    GeoJSON text, instead of Python parsing the full-precision GeoJSON and
    recursively rounding it afterwards.

    Note: PostGIS's ``ST_AsGeoJSON`` raises ``GeoJson: geometry not supported``
    for a GeometryCollection whose sole member is itself a GeometryCollection.
    Don't construct geometries like that (Django's GeometryCollectionField
    already wraps every geometry once; wrapping it again is redundant, not
    something real harvested/contributed data ever does).
    """
    return queryset.annotate(**{out_field: AsGeoJSON(geo_field, precision=precision)})
