# SPDX-FileCopyrightText: 2026 OPTIMETA and KOMET projects <https://projects.tib.eu/komet>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Offline point-in-polygon global-region lookup for ``Work``.

Associates a work with the continents and oceans its geometry touches by
intersecting the geometry against the :class:`works.models.GlobalRegion`
outlines (loaded via ``manage.py load_global_regions``). The mirror of
:mod:`works.services.countries`: deterministic, needs no network, and naturally
multi-valued — a polygon spanning the Atlantic coast of Europe returns both the
continent and the ocean.

Unlike the country join there is **no coastal buffer-snap**: continents and
oceans tile the whole globe, so a coastal point already falls inside an ocean
region, and snapping would risk pulling a work into two adjacent continents.

Used by the ``Work`` post-save signal (``works.signals.assign_work_regions``)
and the recurring backfill sweep (``works.tasks.backfill_work_regions``).
"""

from __future__ import annotations

from django.utils import timezone

#: Outline dataset backing the ``GlobalRegion`` table; recorded in provenance.
REGION_OUTLINE_SOURCE = "global_regions"


def lookup_regions(geom) -> tuple[list, dict | None]:
    """Resolve ``geom`` to ``GlobalRegion`` rows and a provenance record.

    Returns ``(regions, provenance)``. ``provenance`` is ``None`` when nothing
    matched; otherwise a dict describing the join. This is the transparency
    record persisted to ``Work.provenance['regions']`` by the post-save signal
    and backfill sweep.

    The input geometry is repaired with PostGIS ``ST_MakeValid`` first, so a
    self-intersecting or otherwise invalid work geometry no longer crashes the
    spatial predicate with ``TopologyException`` (points/lines pass through
    unchanged).
    """
    if not geom or geom.empty:
        return [], None
    from django.contrib.gis.db.models import GeometryField
    from django.contrib.gis.db.models.functions import MakeValid
    from django.db.models import Value

    from works.models import GlobalRegion

    geom_field = GeometryField(srid=4326)
    valid = MakeValid(Value(geom, output_field=geom_field))
    matches = list(GlobalRegion.objects.filter(geom__intersects=valid))
    if not matches:
        return [], None
    return matches, _provenance(matches)


def regions_for_geometry(geom) -> list:
    """Return the ``GlobalRegion`` rows whose outline intersects ``geom``.

    Thin wrapper over :func:`lookup_regions` that discards the provenance
    record. Empty list for empty/absent geometry, works with no polygon match,
    or when the ``GlobalRegion`` table has not been loaded.
    """
    return lookup_regions(geom)[0]


def _provenance(regions) -> dict:
    return {
        "source": REGION_OUTLINE_SOURCE,
        "method": "intersects",
        "regions": [{"name": r.name, "region_type": r.get_region_type_display()} for r in regions],
        "assigned_at": timezone.now().isoformat(),
    }
