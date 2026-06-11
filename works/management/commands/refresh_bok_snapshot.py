# SPDX-FileCopyrightText: 2026 OPTIMETA and KOMET projects <https://projects.tib.eu/komet>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Fetch the EO4GEO Body of Knowledge snapshot and prime the cache.

Usage:
    python manage.py refresh_bok_snapshot                          # use settings.BOK_VERSION
    python manage.py refresh_bok_snapshot --bok-version v9          # override version
    python manage.py refresh_bok_snapshot --dry-run                # don't write cache

The cache is otherwise filled lazily on first request; this command is
the explicit ops hook for warming the cache after a deploy or for cron.
"""

from django.conf import settings
from django.core.cache import cache
from django.core.management.base import BaseCommand

from works.bok import client as bok_client


class Command(BaseCommand):
    help = "Fetch and cache the EO4GEO Body of Knowledge snapshot."

    def add_arguments(self, parser):
        parser.add_argument(
            "--bok-version",
            dest="bok_version",
            default=None,
            help="BoK version to fetch (e.g. 'v9', 'v3'). Defaults to OPTIMAP_BOK_VERSION.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Fetch and report concept count without writing the cache.",
        )

    def handle(self, *args, **opts):
        version = opts.get("bok_version") or settings.BOK_VERSION
        dry_run = opts["dry_run"]

        self.stdout.write(f"Fetching EO4GEO BoK snapshot (version={version})…")
        snapshot = bok_client.fetch_bok_snapshot(version)
        count = len(snapshot)

        if dry_run:
            self.stdout.write(self.style.WARNING(
                f"Dry run — fetched {count} concepts, cache NOT written."
            ))
            return

        key = bok_client._cache_key(version)
        cache.set(key, snapshot, timeout=bok_client.BOK_CACHE_TIMEOUT)
        self.stdout.write(self.style.SUCCESS(
            f"Cached {count} concepts at key {key!r}."
        ))
