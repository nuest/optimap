# SPDX-FileCopyrightText: 2026 OPTIMETA and KOMET projects <https://projects.tib.eu/komet>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests for `python manage.py reset_harvest_schedules`."""

from datetime import timedelta
from io import StringIO

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone
from django_q.models import Schedule

from works.models import Source


def _make_source(name, interval=120):
    return Source.objects.create(
        name=name,
        url_field=f"http://example.org/{name}",
        harvest_interval_minutes=interval,
    )


class ResetHarvestSchedulesTest(TestCase):
    def test_handles_empty_db(self):
        out = StringIO()
        call_command("reset_harvest_schedules", stdout=out)
        self.assertIn("No sources", out.getvalue())

    def test_resets_stale_next_run(self):
        # Simulate the buggy state: a Schedule with next_run=now (the old default
        # produced by the pre-fix Source.save()).
        source = _make_source("StaleA", interval=120)
        sched = Schedule.objects.get(name=f"Harvest Source {source.id}")
        sched.next_run = timezone.now()  # the bad state we want to recover from
        sched.save()

        before = timezone.now()
        call_command("reset_harvest_schedules", "--no-stagger", stdout=StringIO())

        sched_after = Schedule.objects.get(name=f"Harvest Source {source.id}")
        # With --no-stagger, next_run = now + interval
        self.assertGreaterEqual(sched_after.next_run, before + timedelta(minutes=119))

    def test_stagger_spreads_next_runs(self):
        # 4 sources at 120-minute interval, staggered = step of 30 minutes between them.
        for i, name in enumerate(["A", "B", "C", "D"]):
            _make_source(name, interval=120)

        call_command("reset_harvest_schedules", stdout=StringIO())

        runs = sorted(
            Schedule.objects.filter(name__startswith="Harvest Source ").values_list("next_run", flat=True)
        )
        self.assertEqual(len(runs), 4)
        # Spread should be roughly 0/30/60/90 minutes from the first run.
        spread = (runs[-1] - runs[0]).total_seconds() / 60
        self.assertGreater(spread, 60, f"Expected staggered next_runs, got spread of {spread} min")

    def test_dry_run_does_not_modify(self):
        source = _make_source("DryRun", interval=120)
        sched_id_before = Schedule.objects.get(name=f"Harvest Source {source.id}").id
        next_run_before = Schedule.objects.get(name=f"Harvest Source {source.id}").next_run

        out = StringIO()
        call_command("reset_harvest_schedules", "--dry-run", stdout=out)

        sched_after = Schedule.objects.get(name=f"Harvest Source {source.id}")
        self.assertEqual(sched_after.id, sched_id_before)
        self.assertEqual(sched_after.next_run, next_run_before)
        self.assertIn("Dry run", out.getvalue())

    def test_clear_manual_deletes_one_off_rows(self):
        source = _make_source("ManualHost", interval=120)
        Schedule.objects.create(
            name=f"Manual Harvest Source {source.id}",
            func="works.tasks.harvest_oai_endpoint",
            args=str(source.id),
            schedule_type=Schedule.ONCE,
            next_run=timezone.now(),
        )
        self.assertEqual(
            Schedule.objects.filter(name__startswith="Manual Harvest Source ").count(), 1
        )

        call_command("reset_harvest_schedules", "--clear-manual", stdout=StringIO())

        self.assertEqual(
            Schedule.objects.filter(name__startswith="Manual Harvest Source ").count(), 0
        )

    def test_clear_manual_is_opt_in(self):
        source = _make_source("ManualKept", interval=120)
        Schedule.objects.create(
            name=f"Manual Harvest Source {source.id}",
            func="works.tasks.harvest_oai_endpoint",
            args=str(source.id),
            schedule_type=Schedule.ONCE,
            next_run=timezone.now(),
        )

        call_command("reset_harvest_schedules", stdout=StringIO())

        self.assertEqual(
            Schedule.objects.filter(name__startswith="Manual Harvest Source ").count(), 1,
            "Manual one-off rows must be preserved unless --clear-manual is given",
        )
