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


def _sanitize_polygon_rings(rings):
    """Drop degenerate rings from a single Polygon's coordinate list.

    A valid GeoJSON LinearRing needs >= 4 positions (>= 3 distinct + the
    closing point). Rings with fewer are removed. If the *exterior* ring
    (index 0) is degenerate the whole polygon is unrepresentable, so return
    an empty list and let the caller drop the polygon.

    Returns ``(cleaned_rings, dropped_count)``.
    """
    if not isinstance(rings, list) or not rings:
        return rings, 0

    exterior = rings[0]
    if not isinstance(exterior, list) or len(exterior) < 4:
        # Exterior collapsed — the polygon as a whole is invalid.
        return [], len(rings)

    cleaned = [exterior]
    dropped = 0
    for hole in rings[1:]:
        if isinstance(hole, list) and len(hole) >= 4:
            cleaned.append(hole)
        else:
            dropped += 1
    return cleaned, dropped


def sanitize_geojson_geometry(obj):
    """Recursively drop degenerate polygon rings from a parsed GeoJSON dict.

    Removes LinearRings with fewer than 4 positions (which GEOS rejects with
    ``Invalid number of points in LinearRing``). A common source is
    client-side simplification collapsing a small interior ring (e.g. the
    foreign enclaves inside Switzerland's boundary) down to its two repeated
    endpoints. Interior holes that collapse are dropped; a Polygon whose
    exterior ring collapses is dropped entirely. Already-valid input is
    returned unchanged.

    Walks Polygon, MultiPolygon, GeometryCollection, Feature and
    FeatureCollection structures. Returns ``(cleaned_obj, dropped_count)``
    where ``dropped_count`` is the number of rings/polygons removed.
    """
    if not isinstance(obj, dict):
        return obj, 0

    geom_type = obj.get("type")

    if geom_type == "Polygon":
        cleaned_rings, dropped = _sanitize_polygon_rings(obj.get("coordinates"))
        return {**obj, "coordinates": cleaned_rings}, dropped

    if geom_type == "MultiPolygon":
        polygons = obj.get("coordinates") or []
        cleaned_polys = []
        dropped = 0
        for poly in polygons:
            cleaned_rings, d = _sanitize_polygon_rings(poly)
            dropped += d
            if cleaned_rings:
                cleaned_polys.append(cleaned_rings)
        return {**obj, "coordinates": cleaned_polys}, dropped

    if geom_type == "GeometryCollection":
        geometries = obj.get("geometries") or []
        cleaned_geoms = []
        dropped = 0
        for g in geometries:
            cg, d = sanitize_geojson_geometry(g)
            dropped += d
            # Drop polygons that lost their exterior ring entirely.
            if cg.get("type") in ("Polygon", "MultiPolygon") and not cg.get("coordinates"):
                continue
            cleaned_geoms.append(cg)
        return {**obj, "geometries": cleaned_geoms}, dropped

    if geom_type == "Feature":
        cleaned_geom, dropped = sanitize_geojson_geometry(obj.get("geometry"))
        return {**obj, "geometry": cleaned_geom}, dropped

    if geom_type == "FeatureCollection":
        features = obj.get("features") or []
        cleaned_features = []
        dropped = 0
        for f in features:
            cf, d = sanitize_geojson_geometry(f)
            dropped += d
            cleaned_features.append(cf)
        return {**obj, "features": cleaned_features}, dropped

    return obj, 0


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
