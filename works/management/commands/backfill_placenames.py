# SPDX-FileCopyrightText: 2026 OPTIMETA and KOMET projects <https://projects.tib.eu/komet>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Backfill ``Work.placename`` via reverse geocoding.

Country association lives in the ``Work.countries`` M2M — populated separately by
the offline point-in-polygon sweep (``manage.py backfill_work_countries``), not
here. This command only fills the Nominatim placename string.

Iterates over works that have geometry but no placename yet, calls
``works.services.geocoding.geocode_geometry`` (which geocodes each
representative point and returns the lowest common ancestor in the address
hierarchy — see that module for why we don't just geocode the centroid),
and persists the result. Honours Nominatim's 1 req/s courtesy rate limit
between Nominatim hits via the cache + per-point sleep.

Re-runnable. Cache-warm coordinates do not pay the rate-limit sleep.

Usage:
    python manage.py backfill_placenames
    python manage.py backfill_placenames --limit 100
    python manage.py backfill_placenames --force   # also re-fetch existing
    python manage.py backfill_placenames --sleep 1.1
"""

from __future__ import annotations

import time

from django.core.cache import caches
from django.core.management.base import BaseCommand
from django.db.models import Q
from django.utils import timezone

from works.models import Work
from works.services.geocoding import (
    _CACHE_ALIAS,
    _cache_key,
    _common_address,
    _representative_points,
    _reverse_geocode_lookup,
)


class Command(BaseCommand):
    help = "Reverse-geocode Work.placename for works with geometry."

    def add_arguments(self, parser):
        parser.add_argument(
            "--limit",
            type=int,
            default=None,
            help="Max number of works to process (default: all).",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Re-fetch even when placename is already set.",
        )
        parser.add_argument(
            "--sleep",
            type=float,
            default=1.1,
            help="Seconds to sleep between cache-miss requests (default: 1.1, "
            "respects Nominatim's 1 req/s courtesy rate limit).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print actions without writing to the database.",
        )

    def handle(self, *args, **opts):
        limit = opts["limit"]
        force = opts["force"]
        sleep = opts["sleep"]
        dry_run = opts["dry_run"]

        qs = Work.objects.filter(geometry__isnull=False).exclude(geometry__isempty=True)
        if not force:
            qs = qs.filter(Q(placename__isnull=True) | Q(placename=""))
        qs = qs.order_by("id")
        if limit:
            qs = qs[:limit]

        cache = caches[_CACHE_ALIAS]
        total = 0
        updated = 0
        for work in qs.iterator():
            total += 1
            try:
                points = _representative_points(work.geometry)
            except Exception as err:
                self.stderr.write(f"work {work.id}: representative points failed ({err}); skipping")
                continue

            # Walk points by hand so we can sleep between Nominatim hits but
            # skip the sleep on cache hits. Collect both the address dicts
            # (for the LCA reduction) and the per-point match metadata (for
            # the geocoding provenance block — same shape as
            # ``works.services.geocoding.collect_geocoding_matches``).
            addresses = []
            matches = []
            for lat, lon in points:
                key = _cache_key(lat, lon)
                hit = cache.get(key)
                info = _reverse_geocode_lookup(lat, lon)
                if hit is None:
                    # Cache miss (or transient failure) — courtesy delay
                    # before the next Nominatim request.
                    time.sleep(sleep)
                if info and info.get("address"):
                    addresses.append(info["address"])
                    matches.append(
                        {
                            "lat": lat,
                            "lon": lon,
                            "osm_type": info.get("osm_type"),
                            "osm_id": info.get("osm_id"),
                            "place_id": info.get("place_id"),
                            "osm_url": info.get("osm_url"),
                            "display_name": info.get("display_name"),
                        }
                    )

            placename, _country_code = _common_address(addresses)
            self.stdout.write(f"work {work.id}: {len(points)} point(s), {len(addresses)} geocoded → {placename!r}")
            if not addresses:
                # All Nominatim calls failed — leave the work alone.
                continue
            if dry_run:
                continue

            geocoding_block = {
                "gazetteer": "Nominatim",
                "gazetteer_url": "https://nominatim.openstreetmap.org/",
                "placename": placename,
                "n_geocoded": len(addresses),
                "matches": matches,
                "geocoded_at": timezone.now().isoformat(),
            }
            existing_provenance = work.provenance if isinstance(work.provenance, dict) else {}
            new_provenance = dict(existing_provenance)
            new_provenance["geocoding"] = geocoding_block

            changed = work.placename != placename or existing_provenance.get("geocoding") != geocoding_block
            if changed:
                # Use update() to avoid bumping lastUpdate / re-running signals.
                Work.objects.filter(pk=work.pk).update(
                    placename=placename,
                    provenance=new_provenance,
                )
                updated += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Processed {total} work(s); {updated} updated" + (" (dry-run, no writes)" if dry_run else "")
            )
        )
