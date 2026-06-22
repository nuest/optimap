# SPDX-FileCopyrightText: 2026 OPTIMETA and KOMET projects <https://projects.tib.eu/komet>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests for `python manage.py harvest_sources --async`.

The unit tests mock Django-Q's ``async_task`` and assert that the command
enqueues the correct task target + arguments (and refuses options it cannot
honor) without running any harvest synchronously.

The ``online`` test enqueues a real EarthArXiv harvest, runs a Django-Q
cluster to drain the queue, and polls the ``HarvestingEvent`` until it
completes — exercising the full async path end-to-end against a live OAI-PMH
endpoint.
"""

import time
from io import StringIO
from unittest.mock import patch

from django.core.management import CommandError, call_command
from django.test import TestCase, TransactionTestCase, tag

from works.models import HarvestingEvent, Source, Work

# Every synchronous harvest entry point the command imports. In --async mode
# none of these must be called — work is handed off to async_task instead.
SYNC_FUNCS = (
    "harvest_oai_endpoint",
    "harvest_rss_endpoint",
    "harvest_crossref_prefix",
    "harvest_crossref_book_list",
    "harvest_geoscienceworld",
    "harvest_mountain_wetlands",
    "harvest_openalex_source",
)


class HarvestSourcesAsyncUnitTest(TestCase):
    """--async enqueues the right Django-Q task and never harvests inline."""

    def _run_async(self, *args):
        """Call the command in --async mode with all sync harvesters patched.

        Returns the mocked ``async_task`` so callers can assert on the
        enqueued task path / arguments.
        """
        patchers = {name: patch(f"works.management.commands.harvest_sources.{name}") for name in SYNC_FUNCS}
        mocks = {name: p.start() for name, p in patchers.items()}
        self.addCleanup(lambda: [p.stop() for p in patchers.values()])

        with patch("works.management.commands.harvest_sources.async_task", return_value="task-xyz") as async_mock:
            call_command("harvest_sources", *args, "--async", "--create-sources", stdout=StringIO(), stderr=StringIO())

        # No source was harvested synchronously.
        for name, m in mocks.items():
            self.assertFalse(m.called, f"{name} should not run synchronously in --async mode")
        return async_mock

    def test_async_enqueues_oai_task(self):
        async_mock = self._run_async("--source", "eartharxiv")
        async_mock.assert_called_once()
        args, kwargs = async_mock.call_args
        self.assertEqual(args[0], "works.tasks.harvest_oai_endpoint")
        # source.id passed positionally
        source = Source.objects.get(name="EarthArXiv")
        self.assertEqual(args[1], source.id)
        self.assertIn("update_existing", kwargs)
        self.assertIn("max_records", kwargs)
        self.assertIn("user", kwargs)

    def test_async_crossref_includes_crossref_kwargs(self):
        async_mock = self._run_async("--source", "copernicus")
        args, kwargs = async_mock.call_args
        self.assertEqual(args[0], "works.tasks.harvest_crossref_prefix")
        # Crossref-only arguments must survive the async hand-off.
        self.assertIn("source_titles", kwargs)
        self.assertIn("prefix", kwargs)
        self.assertIn("fetch_abstract_from_publisher", kwargs)
        self.assertEqual(kwargs["prefix"], "10.5194")
        self.assertTrue(kwargs["fetch_abstract_from_publisher"])

    def test_async_creates_pending_event_and_passes_event_id(self):
        # The command pre-creates a HarvestingEvent so its PK can be printed
        # and matched in the Django admin; the task receives it as event_id.
        async_mock = self._run_async("--source", "eartharxiv")
        source = Source.objects.get(name="EarthArXiv")
        event = HarvestingEvent.objects.filter(source=source).get()
        self.assertEqual(event.status, "pending")
        _, kwargs = async_mock.call_args
        self.assertEqual(kwargs["event_id"], event.id)

    def test_async_prints_event_id_for_admin_matching(self):
        out = StringIO()
        patchers = {name: patch(f"works.management.commands.harvest_sources.{name}") for name in SYNC_FUNCS}
        [p.start() for p in patchers.values()]
        self.addCleanup(lambda: [p.stop() for p in patchers.values()])
        with patch("works.management.commands.harvest_sources.async_task", return_value="task-xyz"):
            call_command(
                "harvest_sources",
                "--source",
                "eartharxiv",
                "--async",
                "--create-sources",
                stdout=out,
                stderr=out,
            )
        event = HarvestingEvent.objects.get()
        self.assertIn(f"HarvestingEvent #{event.id}", out.getvalue())

    def test_async_propagates_max_records_and_update(self):
        async_mock = self._run_async("--source", "eartharxiv", "--max-records", "7", "--update")
        _, kwargs = async_mock.call_args
        self.assertEqual(kwargs["max_records"], 7)
        self.assertTrue(kwargs["update_existing"])

    def test_async_no_publisher_abstract_reflected_for_crossref(self):
        async_mock = self._run_async("--source", "copernicus", "--no-publisher-abstract")
        _, kwargs = async_mock.call_args
        self.assertFalse(kwargs["fetch_abstract_from_publisher"])

    def test_async_rejects_source_title_for_oai_source(self):
        # --source-title only applies to crossref-prefix sources. The async
        # path refuses to silently drop it and stops before enqueuing anything.
        with patch("works.management.commands.harvest_sources.async_task") as async_mock:
            with self.assertRaises(CommandError) as ctx:
                call_command(
                    "harvest_sources",
                    "--source",
                    "eartharxiv",
                    "--source-title",
                    "Some Journal",
                    "--async",
                    "--create-sources",
                    stdout=StringIO(),
                    stderr=StringIO(),
                )
        self.assertIn("--source-title", str(ctx.exception))
        self.assertFalse(async_mock.called, "nothing must be enqueued when an option cannot be honored")

    def test_async_rejects_no_publisher_abstract_for_oai_source(self):
        with patch("works.management.commands.harvest_sources.async_task") as async_mock:
            with self.assertRaises(CommandError) as ctx:
                call_command(
                    "harvest_sources",
                    "--source",
                    "eartharxiv",
                    "--no-publisher-abstract",
                    "--async",
                    "--create-sources",
                    stdout=StringIO(),
                    stderr=StringIO(),
                )
        self.assertIn("--no-publisher-abstract", str(ctx.exception))
        self.assertFalse(async_mock.called)


@tag("online")
class HarvestSourcesAsyncOnlineTest(TransactionTestCase):
    """End-to-end: enqueue a real EarthArXiv harvest and let a cluster run it.

    Uses TransactionTestCase so the enqueued task is committed and therefore
    visible to the Django-Q worker processes (which run on separate DB
    connections). Soft-skips if the endpoint never yields a completed event in
    time, matching the other ``online`` tests' tolerance for flaky networks.
    """

    SOURCE_KEY = "eartharxiv"
    SOURCE_NAME = "EarthArXiv"
    TIMEOUT_SECONDS = 180

    def test_async_harvest_completes(self):
        from django.db import connections
        from django_q.cluster import Cluster

        out = StringIO()
        call_command(
            "harvest_sources",
            "--source",
            self.SOURCE_KEY,
            "--async",
            "--update",
            "--create-sources",
            "--max-records",
            "5",
            stdout=out,
            stderr=out,
        )
        self.assertIn("Enqueued", out.getvalue())
        source = Source.objects.get(name=self.SOURCE_NAME)

        # Drain the queue with a real cluster, polling for completion. The
        # cluster forks worker processes; close the parent's DB connections
        # first so the fork doesn't share (and then corrupt) a live psycopg2
        # socket. Parent and workers each reconnect lazily afterwards.
        connections.close_all()
        cluster = Cluster()
        cluster.start()
        try:
            event = self._wait_for_event(source)
        finally:
            cluster.stop()
            connections.close_all()

        if event is None:
            self.skipTest(
                f"EarthArXiv async harvest did not complete within {self.TIMEOUT_SECONDS}s "
                "(endpoint slow/unreachable or no worker picked up the task)."
            )

        self.assertEqual(event.status, "completed", f"harvest event ended in status {event.status!r}")
        # A completed harvest of a live source should have produced works.
        self.assertGreater(Work.objects.filter(job=event).count(), 0)

    def _wait_for_event(self, source):
        """Poll until the source has a finished HarvestingEvent, or time out.

        Sleeps in 10s slices (the requested cadence) up to TIMEOUT_SECONDS.
        Returns the finished event, or None on timeout.
        """
        deadline = time.monotonic() + self.TIMEOUT_SECONDS
        while time.monotonic() < deadline:
            time.sleep(10)
            event = HarvestingEvent.objects.filter(source=source).order_by("-started_at").first()
            if event and event.status in ("completed", "failed"):
                return event
        return None
