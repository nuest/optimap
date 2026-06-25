# SPDX-FileCopyrightText: 2026 OPTIMETA and KOMET projects <https://projects.tib.eu/komet>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Backfill ``Work.regions`` via an offline point-in-polygon join.

Thin wrapper over ``works.tasks.backfill_work_regions`` for manual/operator
runs. Links each work that has geometry but no linked regions to every
``GlobalRegion`` (continent or ocean) whose outline intersects its geometry.
Requires ``python manage.py load_global_regions`` to have populated the
``GlobalRegion`` table.

Usage:
    python manage.py backfill_work_regions
    python manage.py backfill_work_regions --limit 100
    python manage.py backfill_work_regions --dry-run
"""

from __future__ import annotations

from django.core.management.base import BaseCommand

from works.tasks import backfill_work_regions


class Command(BaseCommand):
    help = "Link Work.regions via offline point-in-polygon join against GlobalRegion outlines."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=None, help="Max works to process (default: all).")
        parser.add_argument("--dry-run", action="store_true", help="Report counts without writing or emailing.")

    def handle(self, *args, **opts):
        tally = backfill_work_regions(
            trigger_source="manual",
            limit=opts["limit"],
            dry_run=opts["dry_run"],
        )
        self.stdout.write(
            self.style.SUCCESS(
                "Processed {processed}; updated {updated} (multi {multi_region}), "
                "no-match {no_match}, errors {errors}".format(**tally)
                + (" (dry-run, no writes)" if opts["dry_run"] else "")
            )
        )
