# SPDX-FileCopyrightText: 2026 OPTIMETA and KOMET projects <https://projects.tib.eu/komet>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Backfill missing abstract / keywords / authors on existing works from OpenAIRE.

The live harvest pipeline enriches new works automatically (see
``complete_harvest`` → ``enrich_event_from_openaire``); this command covers
works harvested before OpenAIRE enrichment existed, or any subset selected by
collection / DOI prefix / source.

Usage:
    python manage.py enrich_openaire                         # all works missing a target field
    python manage.py enrich_openaire --collection agile-gi   # AGILE GI works only
    python manage.py enrich_openaire --doi-prefix 10.1007/978- --limit 20
    python manage.py enrich_openaire --throttle 1            # with a token set (7200/hour)
    python manage.py enrich_openaire --dry-run               # query OpenAIRE, write nothing

OpenAIRE is rate-limited to 60 requests/hour anonymously; set
OPTIMAP_OPENAIRE_TOKEN and lower --throttle for larger backfills.
"""

import logging
import time

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db.models import Q

from works.harvesting.openaire import enrich_work_from_openaire
from works.harvesting.sessions import _openaire_session
from works.models import Work

logger = logging.getLogger(__name__)

_MISSING_TARGET_FIELD = (
    Q(abstract__isnull=True)
    | Q(abstract="")
    | Q(keywords__isnull=True)
    | Q(keywords=[])
    | Q(authors__isnull=True)
    | Q(authors=[])
)


class Command(BaseCommand):
    help = "Enrich works that lack an abstract/keywords/authors with metadata from OpenAIRE"

    def add_arguments(self, parser):
        parser.add_argument(
            "--collection",
            default=None,
            help="Limit to works in this collection identifier (e.g. agile-gis).",
        )
        parser.add_argument(
            "--doi-prefix",
            default=None,
            help="Limit to works whose DOI starts with this prefix (e.g. '10.1007/978-').",
        )
        parser.add_argument(
            "--source",
            default=None,
            help="Limit to works from this Source (numeric id or exact name).",
        )
        parser.add_argument("--limit", type=int, default=None, help="Maximum number of works to process.")
        parser.add_argument(
            "--throttle",
            type=float,
            default=None,
            metavar="SECONDS",
            help="Seconds between OpenAIRE requests (default: OPTIMAP_OPENAIRE_ENRICH_THROTTLE).",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Query OpenAIRE even for works that already have all target fields.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Query OpenAIRE and report, but do not write to the database.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        limit = options["limit"]
        force = options["force"]
        throttle = options["throttle"]
        if throttle is None:
            throttle = settings.OPTIMAP_OPENAIRE_ENRICH_THROTTLE

        qs = Work.objects.filter(doi__isnull=False).exclude(doi="")
        if not force:
            qs = qs.filter(_MISSING_TARGET_FIELD)
        if options["collection"]:
            qs = qs.filter(collections__identifier=options["collection"])
        if options["doi_prefix"]:
            qs = qs.filter(doi__startswith=options["doi_prefix"])
        if options["source"]:
            source = options["source"]
            qs = qs.filter(source_id=int(source)) if source.isdigit() else qs.filter(source__name=source)
        qs = qs.order_by("id").distinct()
        if limit:
            qs = qs[:limit]

        total = qs.count()
        if dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN — no changes will be saved"))
        self.stdout.write(f"Processing {total} work(s) against OpenAIRE...")

        session = _openaire_session()
        processed = updated = no_match = failed = 0
        try:
            for work in qs.iterator(chunk_size=50):
                processed += 1
                doi = work.doi or ""
                try:
                    enrich_work_from_openaire(work, session=session, save=not dry_run)
                except Exception as exc:
                    logger.warning("OpenAIRE enrich failed for work %s (%s): %s", work.id, doi, exc)
                    failed += 1
                    if processed < total and throttle:
                        time.sleep(throttle)
                    continue

                provenance = work.provenance if isinstance(work.provenance, dict) else {}
                match = provenance.get("openaire_match") or {}
                if match.get("status") != "matched":
                    self.stdout.write(f"  [{work.id}] {doi} — no OpenAIRE match")
                    no_match += 1
                else:
                    events = provenance.get("events") or []
                    filled = (events[-1].get("fields_filled") if events else None) or []
                    if filled:
                        self.stdout.write(self.style.SUCCESS(f"  [{work.id}] {doi} — filled {filled}"))
                        updated += 1
                    else:
                        self.stdout.write(f"  [{work.id}] {doi} — matched, nothing to fill")

                if processed < total and throttle:
                    time.sleep(throttle)
        finally:
            session.close()

        self.stdout.write(self.style.SUCCESS("\nDone."))
        self.stdout.write(f"  Processed : {processed}")
        self.stdout.write(self.style.SUCCESS(f"  Updated   : {updated}"))
        self.stdout.write(f"  No match  : {no_match}")
        if failed:
            self.stdout.write(self.style.ERROR(f"  Failed    : {failed}"))
        if dry_run:
            self.stdout.write(self.style.WARNING("(DRY RUN — no changes saved)"))
