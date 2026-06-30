# SPDX-FileCopyrightText: 2025 OPTIMETA and KOMET projects <https://projects.tib.eu/komet>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Backfill OpenAlex enrichment for works that are missing it.

Typical use: re-enrich works whose OpenAlex match was dropped due to 429
rate-limit errors during a large harvest run. After configuring
``OPTIMAP_OPENALEX_API_KEY`` (or storing the key in Django admin → Service
tokens → OpenAlex API), run:

    python manage.py backfill_openalex               # all works missing openalex_id
    python manage.py backfill_openalex --all         # re-enrich even already-matched works
    python manage.py backfill_openalex --source essoar --limit 200 --dry-run
"""

import logging
import time

from django.core.management.base import BaseCommand

from works.harvesting.enrichment import apply_enrichment
from works.harvesting.openalex import build_openalex_fields
from works.models import Work

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Backfill OpenAlex enrichment for works missing it (e.g. after 429 rate-limit errors)"

    def add_arguments(self, parser):
        parser.add_argument(
            "--all",
            action="store_true",
            help="Re-enrich all live works, not just those missing an OpenAlex ID",
        )
        parser.add_argument(
            "--source",
            metavar="ID_OR_NAME",
            help="Restrict to works belonging to this Source (numeric id or exact name)",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=None,
            help="Stop after processing this many works",
        )
        parser.add_argument(
            "--throttle",
            type=float,
            default=0.1,
            metavar="SECONDS",
            help="Seconds to wait between works (default: 0.1). Raise to stay within the API budget.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Query OpenAlex and report results but write nothing to the DB",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        process_all = options["all"]
        throttle = options["throttle"]
        limit = options["limit"]
        source_filter = options["source"]

        qs = Work.objects.exclude(status="r")  # skip redirect tombstones

        if source_filter:
            from works.models import Source

            try:
                src = Source.objects.get(pk=int(source_filter))
            except (ValueError, Source.DoesNotExist):
                src = Source.objects.get(name__iexact=source_filter)
            qs = qs.filter(source=src)
            self.stdout.write(f"Restricted to source: {src.name}")

        if not process_all:
            qs = qs.filter(openalex_id__isnull=True)

        total = qs.count()
        if limit:
            qs = qs[:limit]
            self.stdout.write(f"Processing up to {limit} of {total} works...")
        else:
            self.stdout.write(f"Processing {total} works...")

        if dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN — no changes will be saved\n"))

        matched = failed = skipped = 0

        for i, work in enumerate(qs, 1):
            if i % 50 == 0:
                self.stdout.write(
                    f"  {i}/{min(limit or total, total)} — matched {matched}, skipped {skipped}, failed {failed}"
                )

            author = work.authors[0] if work.authors else None
            try:
                openalex_fields, provenance_patch = build_openalex_fields(
                    title=work.title,
                    doi=work.doi,
                    author=author,
                    existing_metadata={"authors": work.authors} if work.authors else {},
                )
            except Exception as exc:
                failed += 1
                logger.error("backfill_openalex: work %s error: %s", work.id, exc)
                continue

            if not openalex_fields or not openalex_fields.get("openalex_id"):
                skipped += 1
                logger.debug("backfill_openalex: no match for work %s (%s)", work.id, work.doi or work.title[:40])
                if throttle:
                    time.sleep(throttle)
                continue

            matched += 1
            self.stdout.write(
                self.style.SUCCESS(f"  ✓ [{work.id}] {work.title[:60]} → {openalex_fields['openalex_id']}")
            )

            if not dry_run:
                fields_filled, _ = apply_enrichment(work, openalex_fields, "openalex")
                # Merge provenance patch into work.provenance.metadata_sources
                if provenance_patch:
                    prov = work.provenance if isinstance(work.provenance, dict) else {}
                    prov.setdefault("metadata_sources", {}).update(provenance_patch)
                    work.provenance = prov
                work.save()

            if throttle:
                time.sleep(throttle)

        self.stdout.write(self.style.SUCCESS(f"\nDone. matched={matched} skipped={skipped} failed={failed}"))
        if dry_run:
            self.stdout.write(self.style.WARNING("(DRY RUN — no changes saved)"))
