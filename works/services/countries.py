# SPDX-FileCopyrightText: 2026 OPTIMETA and KOMET projects <https://projects.tib.eu/komet>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Offline point-in-polygon country lookup for ``Work`` (issue #261).

Associates a work with the countries its geometry touches by intersecting the
geometry against the simplified Natural Earth outlines stored in
:class:`works.models.Country` (loaded via ``manage.py load_countries``). Unlike
the Nominatim reverse-geocoder in :mod:`works.services.geocoding` — which
collapses a transboundary study to a single lowest-common-ancestor country (or
``None``) — this join is deterministic, needs no network, and is naturally
multi-valued: a polygon spanning Germany and Poland returns both.

Used by the ``Work`` post-save signal (``works.signals.assign_work_countries``)
and the recurring backfill sweep (``works.tasks.backfill_work_countries``).
"""

from __future__ import annotations

from django.utils import timezone

#: Outline dataset backing the ``Country`` table; recorded in provenance.
COUNTRY_OUTLINE_SOURCE = "natural_earth"


def lookup_countries(geom, snap_tolerance: float = 0.12) -> tuple[list, dict | None]:
    """Resolve ``geom`` to ``Country`` rows and a provenance record of *how*.

    Returns ``(countries, provenance)``. ``provenance`` is ``None`` when nothing
    matched; otherwise a dict describing the join — its ``method`` is
    ``"intersects"`` for a direct hit or ``"buffer_snap"`` when the match only
    came from the territorial-sea buffer (then ``snap_tolerance_degrees`` is
    included). This is the transparency record persisted to
    ``Work.provenance['countries']`` by the post-save signal and backfill sweep.

    The input geometry is repaired with PostGIS ``ST_MakeValid`` first, so a
    self-intersecting or otherwise invalid work geometry no longer crashes the
    spatial predicate with ``TopologyException`` (points/lines pass through
    unchanged).

    Because the stored Natural Earth outlines are simplified, coastal and small
    -island works often fall just *outside* the polygon. When a strict
    intersection finds nothing, the geometry is buffered by ``snap_tolerance``
    degrees (default ``0.12`` ≈ 12 nautical miles, the Territorial Sea zone) and
    retried, snapping such works onto the nearest country. Snapping is skipped
    for geometries that already intersect (inland / transboundary results are
    unchanged) and for genuinely far-offshore works, which stay unmatched. Pass
    ``snap_tolerance=0`` to disable it.
    """
    if not geom or geom.empty:
        return [], None
    from django.contrib.gis.db.models import GeometryField
    from django.contrib.gis.db.models.functions import MakeValid
    from django.db.models import Func, Value

    from works.models import Country

    geom_field = GeometryField(srid=4326)
    valid = MakeValid(Value(geom, output_field=geom_field))
    matches = list(Country.objects.filter(geom__intersects=valid))
    if matches:
        return matches, _provenance(matches, "intersects")
    if snap_tolerance:
        # ST_Buffer (no Django GIS function wrapper) — snap to nearby outlines.
        buffered = Func(valid, Value(snap_tolerance), function="ST_Buffer", output_field=geom_field)
        matches = list(Country.objects.filter(geom__intersects=buffered))
        if matches:
            return matches, _provenance(matches, "buffer_snap", snap_tolerance)
    return [], None


def countries_for_geometry(geom, snap_tolerance: float = 0.12) -> list:
    """Return the ``Country`` rows whose outline intersects ``geom``.

    Thin wrapper over :func:`lookup_countries` that discards the provenance
    record. Empty list for empty/absent geometry, open-ocean/Antarctica works
    with no polygon match, or when the ``Country`` table has not been loaded.
    """
    return lookup_countries(geom, snap_tolerance)[0]


def _provenance(countries, method: str, snap_tolerance: float | None = None) -> dict:
    info = {
        "source": COUNTRY_OUTLINE_SOURCE,
        "method": method,
        "iso_codes": sorted(c.iso_code for c in countries),
        "assigned_at": timezone.now().isoformat(),
    }
    if method == "buffer_snap":
        info["snap_tolerance_degrees"] = snap_tolerance
    return info
