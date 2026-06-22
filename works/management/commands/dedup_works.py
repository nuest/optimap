# SPDX-FileCopyrightText: 2026 OPTIMETA and KOMET projects <https://projects.tib.eu/komet>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Backfill OpenAlex locations and auto-merge duplicate works.

OpenAlex assigns one ``openalex_id`` per scholarly work; OPTIMAP may hold the
same work harvested from several sources (preprint + published version) as
separate rows. This command does two passes (see ``works/dedup.py``):

1. **Backfill locations** — populate ``Work.locations`` (credited to OpenAlex) on
   every live work that has an ``openalex_id`` but no locations yet, by re-fetching
   the OpenAlex payload. This saves location data to *all* such records, not just
   duplicates.
2. **Merge** — group the works by ``openalex_id`` and merge each group ≥2 into one
   canonical work (the OpenAlex ``primary_location`` version), turning the others
   into ``status='r'`` redirect tombstones.

New harvests do this automatically (``works.harvesting.common._reconcile_dedup``);
this command covers pre-existing data and is also wired as the scheduled
``works.tasks.dedup_sweep``.

Usage:
    python manage.py dedup_works                 # both passes (sync)
    python manage.py dedup_works --locations-only # only backfill locations
    python manage.py dedup_works --source essd    # restrict scope
    python manage.py dedup_works --limit 100 --dry-run
    python manage.py dedup_works --async          # background (needs qcluster)
"""

import logging

from django.core.management.base import BaseCommand
from django_q.humanhash import humanize as humanize_task_id
from django_q.tasks import async_task

from works.models import Source, Work

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Backfill OpenAlex locations and auto-merge duplicate works sharing an OpenAlex id"

    def add_arguments(self, parser):
        parser.add_argument(
            "--source",
            default=None,
            help="Limit to works from this Source (numeric id or exact name).",
        )
        parser.add_argument("--limit", type=int, default=None, help="Max works to backfill locations for.")
        parser.add_argument(
            "--locations-only",
            action="store_true",
            help="Only populate locations; do not merge duplicates.",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Re-fetch and overwrite locations even when already present.",
        )
        parser.add_argument("--dry-run", action="store_true", help="Report counts; write nothing.")
        parser.add_argument(
            "--async",
            dest="run_async",
            action="store_true",
            help="Enqueue works.tasks.dedup_sweep on the Django-Q cluster instead of running inline.",
        )

    def _build_queryset(self, source):
        qs = Work.objects.all()
        if source:
            if str(source).isdigit():
                qs = qs.filter(source_id=int(source))
            else:
                src = Source.objects.filter(name=source).first()
                if src is None:
                    raise SystemExit(f"No Source with id/name '{source}'.")
                qs = qs.filter(source=src)
        return qs

    def handle(self, *args, **options):
        source = options["source"]
        limit = options["limit"]
        locations_only = options["locations_only"]
        force = options["force"]
        dry_run = options["dry_run"]
        run_async = options["run_async"]

        if run_async:
            task_id = async_task(
                "works.tasks.dedup_sweep",
                locations_only=locations_only,
                force=force,
                limit=limit,
            )
            self.stdout.write(self.style.SUCCESS(f"Enqueued dedup_sweep as task {humanize_task_id(task_id)}."))
            return

        from works.dedup import sweep

        queryset = self._build_queryset(source)
        stats = sweep(
            queryset=queryset,
            locations_only=locations_only,
            force=force,
            dry_run=dry_run,
            limit=limit,
            on_progress=self.stdout.write,
        )
        prefix = "[dry-run] " if dry_run else ""
        self.stdout.write(
            self.style.SUCCESS(
                f"{prefix}locations filled: {stats['locations_filled']}, "
                f"groups merged: {stats['groups_merged']}, "
                f"works redirected: {stats['works_redirected']}"
            )
        )
