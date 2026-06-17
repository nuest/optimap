# SPDX-FileCopyrightText: 2025 OPTIMETA and KOMET projects <https://projects.tib.eu/komet>
# SPDX-License-Identifier: GPL-3.0-or-later

# W3C SDW-BP 6: cap coordinate precision so we don't imply sub-meter accuracy
# that the underlying metadata doesn't support.  5 decimal places ≈ 1.1 m at
# the equator — sufficient for publication-level spatial coverage.
COORDINATE_PRECISION = 5


def round_geojson_coordinates(obj, precision=COORDINATE_PRECISION):
    """Recursively round every float in a parsed GeoJSON dict/list."""
    if isinstance(obj, list):
        return [round_geojson_coordinates(v, precision) for v in obj]
    if isinstance(obj, float):
        return round(obj, precision)
    if isinstance(obj, dict):
        return {k: round_geojson_coordinates(v, precision) for k, v in obj.items()}
    return obj
