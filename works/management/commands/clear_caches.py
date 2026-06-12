# SPDX-FileCopyrightText: 2026 OPTIMETA and KOMET projects <https://projects.tib.eu/komet>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Clear Django caches.

Django still ships no built-in ``clearcache`` command — see the
long-running discussion at
https://stackoverflow.com/questions/5942759/best-place-to-clear-cache-when-restarting-django-server.
Running ``cache.clear()`` in ``manage.py shell -c …`` works but is
brittle in deployment scripts (multi-line quoting, escape handling) and
opaque to read months later. This command makes the operation explicit,
idempotent, and scriptable.

Usage:
    python manage.py clear_caches                    # clear all configured caches
    python manage.py clear_caches --cache memory     # clear only 'memory' (repeatable)
    python manage.py clear_caches --exclude default  # clear all except 'default'
                                                     # (preserves login-magic tokens
                                                     # and email-change confirmations)
    python manage.py clear_caches --dry-run          # report what would be cleared

Production notes:
- The ``memory`` (``LocMemCache``) backend is per-process; restarting the
  application server already clears it. Re-clearing it is harmless.
- The ``default`` (``DatabaseCache``, table ``cache``) backend persists
  across restarts and stores login-magic tokens, email-change confirmations,
  and GeoRSS feed bodies. Clearing it invalidates any in-flight magic
  links — pass ``--exclude default`` if a routine deploy should leave
  active tokens alone.
- Browsers may still serve cached copies of pages (``Cache-Control:
  max-age=…``) and static files (``expires 30d`` on ``/static/``) regardless
  of server-side state. A hard refresh bypasses both on the client side.
"""

from django.core.cache import caches
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Clear Django caches (all by default; --cache / --exclude to scope)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--cache",
            action="append",
            default=[],
            metavar="ALIAS",
            help="Clear only this cache (repeatable). Mutually exclusive with --exclude.",
        )
        parser.add_argument(
            "--exclude",
            action="append",
            default=[],
            metavar="ALIAS",
            help="Clear every cache except this one (repeatable). Mutually exclusive with --cache.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report which caches would be cleared without clearing them.",
        )

    def handle(self, *args, **opts):
        only = opts["cache"]
        exclude = opts["exclude"]
        dry_run = opts["dry_run"]

        if only and exclude:
            raise CommandError("--cache and --exclude are mutually exclusive.")

        configured = list(caches)
        unknown = [a for a in (only + exclude) if a not in configured]
        if unknown:
            raise CommandError(f"Unknown cache alias(es): {', '.join(unknown)}. Configured: {', '.join(configured)}")

        if only:
            targets = only
        elif exclude:
            targets = [a for a in configured if a not in exclude]
        else:
            targets = configured

        for alias in targets:
            backend = caches[alias].__class__.__name__
            if dry_run:
                self.stdout.write(f"Would clear: {alias} ({backend})")
            else:
                caches[alias].clear()
                self.stdout.write(self.style.SUCCESS(f"Cleared: {alias} ({backend})"))

        if not dry_run:
            self.stdout.write(self.style.SUCCESS(f"Done — cleared {len(targets)} cache(s)."))
