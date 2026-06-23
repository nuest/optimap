# SPDX-FileCopyrightText: 2026 OPTIMETA and KOMET projects <https://projects.tib.eu/komet>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Reset Django-Q schedules for all Sources.

Rebuilds the recurring `Harvest Source <id>` schedules so each one's
`next_run` is properly deferred (rather than `timezone.now`, which used to
queue every source to fire at once on the next cluster tick).

By default, next_runs are staggered evenly across the smallest harvest
interval found among sources, so the cluster doesn't get a thundering
herd at the first deferred tick either.

Usage:
    python manage.py reset_harvest_schedules
    python manage.py reset_harvest_schedules --dry-run
    python manage.py reset_harvest_schedules --no-stagger
    python manage.py reset_harvest_schedules --clear-manual
"""

from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone
from django_q.models import Schedule

from works.models import Source


class Command(BaseCommand):
    help = (
        "Rebuild Django-Q recurring schedules for all Sources with proper "
        "`next_run` values. Use after a bulk source-insert that left every "
        "schedule firing immediately."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print what would change without writing.",
        )
        parser.add_argument(
            "--no-stagger",
            action="store_true",
            help=(
                "Set every next_run to `now + interval`. By default, next_runs "
                "are staggered across the smallest interval to avoid a herd."
            ),
        )
        parser.add_argument(
            "--clear-manual",
            action="store_true",
            help=(
                "Also delete one-off `Manual Harvest Source <id>` schedules "
                "left over from the admin 'Schedule harvesting' action."
            ),
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        stagger = not options["no_stagger"]
        clear_manual = options["clear_manual"]

        # Interval-0 sources are "no automatic harvest" (matches Source.save,
        # which never creates a recurring schedule for them) — skip them so the
        # seeded "User contributions" source (interval 0) doesn't get scheduled
        # or poison the stagger math (min_interval=0 → zero spread).
        sources = [s for s in Source.objects.order_by("id") if s.harvest_interval_minutes > 0]
        if not sources:
            self.stdout.write(self.style.WARNING("No sources with a harvest interval; nothing to do."))
            return

        now = timezone.now()
        min_interval = min(s.harvest_interval_minutes for s in sources)
        # When staggered, spread the first runs evenly across one min_interval window.
        # When not staggered, every source's next run is `now + its own interval`.
        step = (min_interval / len(sources)) if stagger else None

        prefix = "[dry-run] " if dry_run else ""
        self.stdout.write(
            self.style.SUCCESS(
                f"{prefix}Resetting recurring schedules for {len(sources)} source(s) "
                f"({'staggered' if stagger else 'no stagger'}). Min interval: {min_interval} min."
            )
        )

        rebuilt = 0
        for index, source in enumerate(sources):
            name = f"Harvest Source {source.id}"
            if stagger:
                next_run = now + timedelta(minutes=step * index)
            else:
                next_run = now + timedelta(minutes=source.harvest_interval_minutes)

            existing = Schedule.objects.filter(name=name).first()
            old_next = existing.next_run.isoformat() if existing and existing.next_run else "—"
            self.stdout.write(
                f"  {prefix}{name:30} interval={source.harvest_interval_minutes:>6}m  "
                f"next_run: {old_next} -> {next_run.isoformat()}"
            )
            if dry_run:
                continue
            if existing:
                existing.delete()
            Schedule.objects.create(
                func="works.tasks.harvest_oai_endpoint",
                args=str(source.id),
                schedule_type=Schedule.MINUTES,
                minutes=source.harvest_interval_minutes,
                next_run=next_run,
                name=name,
                intended_date_kwarg="scheduled_for",
            )
            rebuilt += 1

        cleared = 0
        if clear_manual:
            qs = Schedule.objects.filter(name__startswith="Manual Harvest Source ")
            cleared = qs.count()
            self.stdout.write(f"  {prefix}Deleting {cleared} 'Manual Harvest Source ...' one-off schedule(s).")
            if not dry_run:
                qs.delete()

        if dry_run:
            self.stdout.write(
                self.style.WARNING(
                    f"\nDry run complete. Would have rebuilt {len(sources)} schedule(s)"
                    + (f" and cleared {cleared} manual one-off(s)." if clear_manual else ".")
                )
            )
        else:
            self.stdout.write(
                self.style.SUCCESS(
                    f"\nRebuilt {rebuilt} schedule(s)"
                    + (f" and cleared {cleared} manual one-off(s)." if clear_manual else ".")
                )
            )
