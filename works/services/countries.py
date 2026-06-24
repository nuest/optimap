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


def countries_for_geometry(geom) -> list:
    """Return the ``Country`` rows whose outline intersects ``geom``.

    Empty list for empty/absent geometry, ocean/Antarctica points with no
    polygon match, or when the ``Country`` table has not been loaded.
    """
    if not geom or geom.empty:
        return []
    from works.models import Country

    return list(Country.objects.filter(geom__intersects=geom))
