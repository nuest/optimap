# SPDX-FileCopyrightText: 2026 OPTIMETA and KOMET projects <https://projects.tib.eu/komet>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Test helpers for populating the ``Work.regions`` M2M.

In production ``Work.regions`` is filled by the ``assign_work_regions`` post-save
signal (gated by ``OPTIMAP_GEOCODE_WORKS_ON_SAVE``, forced off under the test
runner) and the ``backfill_work_regions`` sweep. Tests that load works from a
fixture, or create them with the gate off, must therefore populate the M2M
themselves before exercising any region feed page, regional subscription email,
or ``by_continent``/``by_ocean`` statistic — all of which now read this M2M
instead of intersecting geometry on the fly.

This module is **not** named ``test*`` so the runner does not collect it.
"""

from __future__ import annotations


def link_all_work_regions():
    """Link every geometry-bearing ``Work`` to its intersecting ``GlobalRegion``s.

    Uses the same offline resolver as the signal/sweep, so the linked set matches
    production. Cheap enough to call from ``setUpTestData`` or mid-test.
    """
    from works.models import Work
    from works.services.regions import regions_for_geometry

    for work in Work.objects.filter(geometry__isnull=False).exclude(geometry__isempty=True):
        work.regions.set(regions_for_geometry(work.geometry))
