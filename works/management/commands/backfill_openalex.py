"""
Management command to backfill OpenAlex data for existing publications.

Usage:
    python manage.py backfill_openalex --all
    python manage.py backfill_openalex --limit 100
    python manage.py backfill_openalex --only-missing
"""

import logging
from django.core.management.base import BaseCommand
from works.models import Work
from works.openalex_matcher import get_openalex_matcher

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Backfill OpenAlex data for existing publications'

    def add_arguments(self, parser):
        parser.add_argument(
            '--all',
            action='store_true',
            help='Process all publications (re-match even if OpenAlex ID exists)',
        )
        parser.add_argument(
            '--only-missing',
            action='store_true',
            help='Only process publications without OpenAlex ID (default)',
        )
        parser.add_argument(
            '--limit',
            type=int,
            default=None,
            help='Maximum number of publications to process',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be done without making changes',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        limit = options['limit']
        process_all = options['all']

        # Build query
        query = Work.objects.all()

        if not process_all:
            # Default: only process publications without OpenAlex ID
            query = query.filter(openalex_id__isnull=True)

        # Apply limit
        if limit:
            query = query[:limit]

        total = query.count()
        self.stdout.write(self.style.SUCCESS(f'\nProcessing {total} publications...\n'))

        if dry_run:
            self.stdout.write(self.style.WARNING('DRY RUN MODE - No changes will be saved\n'))

        matcher = get_openalex_matcher()

        processed = 0
        matched = 0
        partial = 0
        failed = 0

        for work in query:
            processed += 1

            if processed % 10 == 0:
                self.stdout.write(f'Progress: {processed}/{total} ({matched} matched, {partial} partial, {failed} failed)')

            try:
                # Extract author if available (simplified - could be improved)
                author = None
                # You could extract author from abstract or other fields if needed

                # Try to match
                openalex_data, partial_matches = matcher.match_publication(
                    title=work.title,
                    doi=work.doi,
                    author=author
                )

                if openalex_data:
                    # Perfect match found
                    matched += 1
                    self.stdout.write(
                        self.style.SUCCESS(
                            f'  ✓ [{work.id}] Matched: {work.title[:50]}... -> {openalex_data.get("openalex_id", "N/A")}'
                        )
                    )

                    if not dry_run:
                        # Update work with OpenAlex data
                        for field, value in openalex_data.items():
                            setattr(work, field, value)
                        work.save()

                elif partial_matches:
                    # Partial matches found
                    partial += 1
                    self.stdout.write(
                        self.style.WARNING(
                            f'  ~ [{work.id}] Partial matches: {work.title[:50]}... ({len(partial_matches)} candidates)'
                        )
                    )

                    if not dry_run:
                        work.openalex_id = None
                        work.openalex_match_info = partial_matches
                        work.save()

                else:
                    # No match found
                    failed += 1
                    if work.doi:
                        # Log as warning if DOI exists - OpenAlex should have it
                        logger.warning(f'No OpenAlex match for work {work.id} with DOI {work.doi}: {work.title[:50]}')
                    else:
                        logger.debug(f'No OpenAlex match for work {work.id}: {work.title[:50]}')

            except Exception as e:
                failed += 1
                logger.error(f'Error processing work {work.id}: {str(e)}')
                self.stdout.write(
                    self.style.ERROR(
                        f'  ✗ [{work.id}] Error: {work.title[:50]}... - {str(e)}'
                    )
                )

        # Print summary
        self.stdout.write(self.style.SUCCESS(f'\n{"="*70}'))
        self.stdout.write(self.style.SUCCESS('Backfill Complete'))
        self.stdout.write(self.style.SUCCESS(f'{"="*70}\n'))
        self.stdout.write(f'Total processed: {processed}')
        self.stdout.write(self.style.SUCCESS(f'Perfect matches: {matched}'))
        self.stdout.write(self.style.WARNING(f'Partial matches: {partial}'))
        self.stdout.write(self.style.ERROR(f'No match: {failed}'))

        if dry_run:
            self.stdout.write(self.style.WARNING('\n(DRY RUN - No changes were saved)'))
