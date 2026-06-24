# SPDX-FileCopyrightText: 2026 OPTIMETA and KOMET projects <https://projects.tib.eu/komet>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Backfill ``Work.countries`` via an offline point-in-polygon join (issue #261).

Thin wrapper over ``works.tasks.backfill_work_countries`` for manual/operator
runs. Links each work that has geometry but no linked countries to every
``Country`` whose Natural Earth outline intersects its geometry. Requires
``python manage.py load_countries`` to have populated the ``Country`` table.

Usage:
    python manage.py backfill_work_countries
    python manage.py backfill_work_countries --limit 100
    python manage.py backfill_work_countries --dry-run
"""

from __future__ import annotations

from django.core.management.base import BaseCommand

from works.tasks import backfill_work_countries


class Command(BaseCommand):
    help = "Link Work.countries via offline point-in-polygon join against Country outlines."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=None, help="Max works to process (default: all).")
        parser.add_argument("--dry-run", action="store_true", help="Report counts without writing or emailing.")

    def handle(self, *args, **opts):
        tally = backfill_work_countries(
            trigger_source="manual",
            limit=opts["limit"],
            dry_run=opts["dry_run"],
        )
        self.stdout.write(
            self.style.SUCCESS(
                "Processed {processed}; updated {updated} (multi {multi_country}), "
                "no-match {no_match}, errors {errors}".format(**tally)
                + (" (dry-run, no writes)" if opts["dry_run"] else "")
            )
        )
