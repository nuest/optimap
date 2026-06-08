# SPDX-FileCopyrightText: 2026 OPTIMETA and KOMET projects <https://projects.tib.eu/komet>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Backfill EO4GEO BoK concepts for already-harvested AGILE GISS works.

Usage:
    python manage.py extract_agile_bok
    python manage.py extract_agile_bok --limit 20 --throttle 3
    python manage.py extract_agile_bok --force    # re-extract even if bok_concepts set
    python manage.py extract_agile_bok --dry-run  # log without writing
"""

import logging
import time

from django.core.management.base import BaseCommand

from works.harvesting.bok_pdf import agile_giss_doi_to_pdf_url, extract_bok_from_agile_pdf
from works.models import Work
from works.utils.provenance import append_event

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Extract EO4GEO BoK concepts from AGILE GISS full-text PDFs for harvested works"

    def add_arguments(self, parser):
        parser.add_argument(
            "--limit",
            type=int,
            default=None,
            help="Maximum number of works to process.",
        )
        parser.add_argument(
            "--throttle",
            type=float,
            default=2.0,
            metavar="SECONDS",
            help="Seconds to sleep between PDF downloads (default: 2).",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Re-extract even for works that already have bok_concepts set.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Log what would be done without writing to the database.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        limit = options["limit"]
        throttle = options["throttle"]
        force = options["force"]

        qs = Work.objects.filter(doi__startswith="10.5194/agile-giss-").order_by("id")
        if not force:
            # exclude works that already carry bok_concepts (non-null and non-empty)
            qs = qs.exclude(bok_concepts__len__gt=0)
        if limit:
            qs = qs[:limit]

        total = qs.count()
        if dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN — no changes will be saved"))
        self.stdout.write(f"Processing {total} AGILE GISS works...")

        processed = updated = skipped = failed = 0

        for work in qs.iterator(chunk_size=50):
            processed += 1
            doi = work.doi or ""

            if not agile_giss_doi_to_pdf_url(doi):
                logger.debug("Skipping work %s — DOI %r not an AGILE GISS DOI", work.id, doi)
                skipped += 1
                continue

            if work.bok_concepts and not force:
                logger.debug("Skipping work %s — already has bok_concepts", work.id)
                skipped += 1
                continue

            try:
                codes = extract_bok_from_agile_pdf(doi)
            except Exception as exc:
                logger.warning("Extraction error for work %s (%s): %s", work.id, doi, exc)
                failed += 1
                time.sleep(throttle)
                continue

            if not codes:
                self.stdout.write(f"  [{work.id}] {doi} — no BoK concepts found")
            else:
                self.stdout.write(
                    self.style.SUCCESS(f"  [{work.id}] {doi} — {codes}")
                )
                if not dry_run:
                    work.bok_concepts = codes
                    prov = work.provenance if isinstance(work.provenance, dict) else {}
                    prov.setdefault("metadata_sources", {})["bok_concepts"] = "pdf_extraction"
                    work.provenance = prov
                    append_event(
                        work,
                        "bok_pdf_extract",
                        source="pdf",
                        pdf_url=agile_giss_doi_to_pdf_url(doi),
                        codes_found=codes,
                    )
                    work.save(update_fields=["bok_concepts", "provenance"])
                    updated += 1

            if processed < total:
                time.sleep(throttle)

        self.stdout.write(self.style.SUCCESS("\nDone."))
        self.stdout.write(f"  Processed : {processed}")
        self.stdout.write(self.style.SUCCESS(f"  Updated   : {updated}"))
        self.stdout.write(f"  Skipped   : {skipped}")
        if failed:
            self.stdout.write(self.style.ERROR(f"  Failed    : {failed}"))
        if dry_run:
            self.stdout.write(self.style.WARNING("(DRY RUN — no changes saved)"))
