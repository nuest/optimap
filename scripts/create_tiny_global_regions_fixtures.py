#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025 OPTIMETA and KOMET projects <https://projects.tib.eu/komet>
# SPDX-License-Identifier: GPL-3.0-or-later

"""
One-off script: build tiny GeoJSON fixtures for global regions tests.

Reads the full-fidelity geojson files used by load_global_regions:
  works/management/commands/goas_v01_simplified.geojson  (~4.5 MB)
  works/management/commands/world_continents.geojson     (~6.3 MB)

Aggressively simplifies each feature (high-tolerance Douglas-Peucker, drop holes,
round to 1 decimal place) and writes minified GeoJSON to:
  tests/fixtures/global_regions/goas_v01_simplified.geojson  (target < 10 KB)
  tests/fixtures/global_regions/world_continents.geojson

Run once when source data changes; the fixtures are committed to git so tests
do not depend on network access.
"""

import json
import os
from pathlib import Path

from shapely.geometry import Polygon, MultiPolygon, mapping, shape
from shapely.ops import unary_union

ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = ROOT / "works" / "management" / "commands"
OUT_DIR = ROOT / "tests" / "fixtures" / "global_regions"

OCEANS_SRC = SRC_DIR / "goas_v01_simplified.geojson"
CONTS_SRC = SRC_DIR / "world_continents.geojson"
OCEANS_OUT = OUT_DIR / "goas_v01_simplified.geojson"
CONTS_OUT = OUT_DIR / "world_continents.geojson"

OCEAN_SIZE_TARGET = 10 * 1024  # 10 KB hard cap from spec


def _round_coords(geom_mapping, ndigits=1):
    """Round all coordinates in a GeoJSON geometry mapping in-place."""

    def _walk(coords):
        if isinstance(coords, (list, tuple)) and coords and isinstance(coords[0], (int, float)):
            return [round(c, ndigits) for c in coords]
        return [_walk(c) for c in coords]

    geom_mapping["coordinates"] = _walk(geom_mapping["coordinates"])
    return geom_mapping


def _drop_holes(geom):
    """Return a MultiPolygon with interior rings removed.

    Always emits MultiPolygon — the GlobalRegion model uses MultiPolygonField,
    and a bare Polygon would fail to round-trip through SpatialProxy on load.
    """
    if geom.geom_type == "Polygon":
        return MultiPolygon([Polygon(geom.exterior)])
    if geom.geom_type == "MultiPolygon":
        return MultiPolygon([Polygon(p.exterior) for p in geom.geoms])
    return geom


def _simplify(geom, tolerance):
    return _drop_holes(geom.simplify(tolerance, preserve_topology=False))


def shrink_features(features, tolerance, ndigits, max_size=None):
    """Apply simplification + rounding; optionally raise tolerance until <= max_size."""
    while True:
        out = []
        for feat in features:
            g = shape(feat["geometry"])
            simplified = _simplify(g, tolerance)
            geom_mapping = _round_coords(mapping(simplified), ndigits=ndigits)
            out.append({
                "type": "Feature",
                "geometry": geom_mapping,
                "properties": feat["properties"],
            })
        payload = {"type": "FeatureCollection", "features": out}
        encoded = json.dumps(payload, separators=(",", ":"))
        if max_size is None or len(encoded.encode("utf-8")) <= max_size:
            return payload, encoded, tolerance
        tolerance *= 1.5


def slim_ocean_props(props):
    """Keep only the name field — load_global_regions only reads it."""
    return {"name": props.get("name") or props.get("Name")}


def slim_continent_props(props):
    """load_global_regions reads CONTINENT (with fallbacks Name/continent)."""
    return {"CONTINENT": props.get("CONTINENT") or props.get("Name") or props.get("continent")}


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # --- Oceans ---
    with OCEANS_SRC.open() as f:
        oceans_in = json.load(f)
    oceans_features = [
        {"geometry": f["geometry"], "properties": slim_ocean_props(f["properties"])}
        for f in oceans_in["features"]
    ]
    oceans_payload, oceans_json, used_tol = shrink_features(
        oceans_features, tolerance=2.0, ndigits=1, max_size=OCEAN_SIZE_TARGET
    )
    OCEANS_OUT.write_text(oceans_json)
    print(f"oceans:    {OCEANS_OUT.relative_to(ROOT)}  "
          f"size={len(oceans_json)} bytes  features={len(oceans_payload['features'])}  "
          f"tolerance={used_tol}")

    # --- Continents ---
    with CONTS_SRC.open() as f:
        conts_in = json.load(f)
    cont_features = [
        {"geometry": f["geometry"], "properties": slim_continent_props(f["properties"])}
        for f in conts_in["features"]
    ]
    conts_payload, conts_json, used_tol = shrink_features(
        cont_features, tolerance=2.0, ndigits=1, max_size=OCEAN_SIZE_TARGET
    )
    CONTS_OUT.write_text(conts_json)
    print(f"continents:{CONTS_OUT.relative_to(ROOT)}  "
          f"size={len(conts_json)} bytes  features={len(conts_payload['features'])}  "
          f"tolerance={used_tol}")


if __name__ == "__main__":
    main()
