# publications/management/commands/harvest_journals.py

"""
Django management command to harvest publications from real OAI-PMH journal sources.

This command harvests from live OAI-PMH endpoints and saves publications to the
current database. It's designed for production use and testing against real sources.

Usage:
    python manage.py harvest_journals --all
    python manage.py harvest_journals --journal essd --max-records 50
    python manage.py harvest_journals --journal geo-leo --journal agile-giss
"""

import logging
from django.core.management.base import BaseCommand, CommandError
from django.contrib.auth import get_user_model
from django.utils import timezone
from publications.models import Source, HarvestingEvent, Publication
from publications.tasks import harvest_oai_endpoint, harvest_rss_endpoint

logger = logging.getLogger(__name__)
User = get_user_model()

# Journal configurations with OAI-PMH and RSS/Atom endpoints
JOURNAL_CONFIGS = {
    'essd': {
        'name': 'Earth System Science Data',
        'url': 'https://oai-pmh.copernicus.org/oai.php?verb=ListRecords&metadataPrefix=oai_dc&set=essd',
        'collection_name': 'ESSD',
        'homepage_url': 'https://essd.copernicus.org/',
        'publisher_name': 'Copernicus Publications',
        'feed_type': 'oai-pmh',
    },
    'agile-giss': {
        'name': 'AGILE-GISS',
        'url': 'https://oai-pmh.copernicus.org/oai.php?verb=ListRecords&metadataPrefix=oai_dc&set=agile-giss',
        'collection_name': 'AGILE-GISS',
        'homepage_url': 'https://www.agile-giscience-series.net/',
        'publisher_name': 'Copernicus Publications',
        'feed_type': 'oai-pmh',
    },
    'geo-leo': {
        'name': 'GEO-LEO e-docs',
        'url': 'https://e-docs.geo-leo.de/server/oai/request?verb=ListRecords&metadataPrefix=oai_dc',
        'collection_name': 'GEO-LEO',
        'homepage_url': 'https://e-docs.geo-leo.de/',
        'publisher_name': 'GEO-LEO',
        'feed_type': 'oai-pmh',
    },
    'scientific-data': {
        'name': 'Scientific Data',
        'url': 'https://www.nature.com/sdata.rss',
        'collection_name': 'Scientific Data',
        'homepage_url': 'https://www.nature.com/sdata/',
        'publisher_name': 'Nature Publishing Group',
        'feed_type': 'rss',
    },
}


class Command(BaseCommand):
    help = 'Harvest publications from real OAI-PMH journal sources into the current database'

    def add_arguments(self, parser):
        parser.add_argument(
            '--journal',
            action='append',
            choices=list(JOURNAL_CONFIGS.keys()),
            help=f'Journal to harvest (choices: {", ".join(JOURNAL_CONFIGS.keys())}). Can be specified multiple times.',
        )
        parser.add_argument(
            '--all',
            action='store_true',
            help='Harvest from all configured journals',
        )
        parser.add_argument(
            '--max-records',
            type=int,
            default=None,
            help='Maximum number of records to harvest per journal (default: unlimited)',
        )
        parser.add_argument(
            '--create-sources',
            action='store_true',
            help='Create Source entries if they don\'t exist (default: use existing sources only)',
        )
        parser.add_argument(
            '--user-email',
            type=str,
            default=None,
            help='Email of user to associate with harvesting events (optional)',
        )
        parser.add_argument(
            '--list',
            action='store_true',
            help='List available journals and exit',
        )

    def handle(self, *args, **options):
        # List journals and exit
        if options['list']:
            self.stdout.write(self.style.SUCCESS('\nAvailable journals for harvesting:\n'))
            for key, config in JOURNAL_CONFIGS.items():
                self.stdout.write(f"  {key:15} - {config['name']}")
                self.stdout.write(f"                  Issue: #{config['issue']}, URL: {config['homepage_url']}")
            return

        # Determine which journals to harvest
        if options['all']:
            journals_to_harvest = list(JOURNAL_CONFIGS.keys())
        elif options['journal']:
            journals_to_harvest = options['journal']
        else:
            raise CommandError(
                'Please specify --all to harvest all journals, or --journal <name> for specific journals.\n'
                'Use --list to see available journals.'
            )

        # Get user if specified
        user = None
        if options['user_email']:
            try:
                user = User.objects.get(email=options['user_email'])
                self.stdout.write(f"Using user: {user.email}")
            except User.DoesNotExist:
                raise CommandError(f"User with email '{options['user_email']}' does not exist")

        max_records = options['max_records']
        create_sources = options['create_sources']

        # Summary statistics
        total_harvested = 0
        total_failed = 0
        results = []

        self.stdout.write(self.style.SUCCESS(f'\n{"="*70}'))
        self.stdout.write(self.style.SUCCESS(f'Starting harvest of {len(journals_to_harvest)} journal(s)'))
        self.stdout.write(self.style.SUCCESS(f'{"="*70}\n'))

        # Harvest each journal
        for journal_key in journals_to_harvest:
            config = JOURNAL_CONFIGS[journal_key]

            self.stdout.write(self.style.WARNING(f'\n--- Harvesting: {config["name"]} ---'))
            self.stdout.write(f'URL: {config["url"]}')
            if max_records:
                self.stdout.write(f'Max records: {max_records}')

            try:
                # Find or create source
                source = self._get_or_create_source(config, create_sources)

                # Harvest based on feed type
                harvest_start = timezone.now()
                feed_type = config.get('feed_type', 'oai-pmh')

                if feed_type == 'rss':
                    self.stdout.write(f'Feed type: RSS/Atom')
                    harvest_rss_endpoint(source.id, user=user, max_records=max_records)
                else:
                    self.stdout.write(f'Feed type: OAI-PMH')
                    harvest_oai_endpoint(source.id, user=user, max_records=max_records)

                # Get results
                event = HarvestingEvent.objects.filter(source=source).latest('started_at')
                pub_count = Publication.objects.filter(job=event).count()

                duration = (timezone.now() - harvest_start).total_seconds()

                if event.status == 'completed':
                    self.stdout.write(self.style.SUCCESS(
                        f'✓ Successfully harvested {pub_count} publications in {duration:.1f}s'
                    ))
                    total_harvested += pub_count
                    results.append({
                        'journal': config['name'],
                        'status': 'success',
                        'count': pub_count,
                        'duration': duration,
                    })
                else:
                    self.stdout.write(self.style.ERROR(
                        f'✗ Harvesting failed with status: {event.status}'
                    ))
                    total_failed += 1
                    results.append({
                        'journal': config['name'],
                        'status': 'failed',
                        'count': 0,
                        'duration': duration,
                    })

                # Show spatial/temporal metadata stats
                spatial_count = Publication.objects.filter(
                    job=event
                ).exclude(geometry__isnull=True).count()

                temporal_count = Publication.objects.filter(
                    job=event
                ).exclude(timeperiod_startdate=[]).count()

                self.stdout.write(
                    f'  Spatial metadata: {spatial_count}/{pub_count} publications'
                )
                self.stdout.write(
                    f'  Temporal metadata: {temporal_count}/{pub_count} publications'
                )

            except Exception as e:
                self.stdout.write(self.style.ERROR(f'✗ Error: {str(e)}'))
                logger.exception(f'Failed to harvest {journal_key}')
                total_failed += 1
                results.append({
                    'journal': config['name'],
                    'status': 'error',
                    'count': 0,
                    'error': str(e),
                })

        # Print summary
        self.stdout.write(self.style.SUCCESS(f'\n{"="*70}'))
        self.stdout.write(self.style.SUCCESS('Harvest Summary'))
        self.stdout.write(self.style.SUCCESS(f'{"="*70}\n'))

        for result in results:
            status_symbol = '✓' if result['status'] == 'success' else '✗'
            status_style = self.style.SUCCESS if result['status'] == 'success' else self.style.ERROR

            if result['status'] == 'success':
                self.stdout.write(status_style(
                    f"{status_symbol} {result['journal']:30} {result['count']:5} publications "
                    f"({result['duration']:.1f}s)"
                ))
            else:
                error_msg = result.get('error', result['status'])
                self.stdout.write(status_style(
                    f"{status_symbol} {result['journal']:30} Failed: {error_msg}"
                ))

        self.stdout.write(f'\nTotal publications harvested: {total_harvested}')
        if total_failed > 0:
            self.stdout.write(self.style.WARNING(f'Failed journals: {total_failed}'))

        self.stdout.write(self.style.SUCCESS(f'\n{"="*70}\n'))

    def _get_or_create_source(self, config, create_if_missing):
        """Get or optionally create a Source for the journal."""
        # Try to find existing source by name or URL
        source = Source.objects.filter(name=config['name']).first()

        if not source:
            source = Source.objects.filter(url_field=config['url']).first()

        if source:
            self.stdout.write(f'Using existing source: {source.name} (ID: {source.id})')
            return source

        if not create_if_missing:
            raise CommandError(
                f"Source '{config['name']}' not found in database. "
                f"Use --create-sources to automatically create it."
            )

        # Create new source
        source = Source.objects.create(
            name=config['name'],
            url_field=config['url'],
            collection_name=config['collection_name'],
            homepage_url=config.get('homepage_url'),
            publisher_name=config.get('publisher_name'),
            is_oa=config.get('is_oa', False),
            harvest_interval_minutes=60 * 24 * 7,  # Weekly
        )

        self.stdout.write(self.style.SUCCESS(
            f'Created new source: {source.name} (ID: {source.id})'
        ))

        return source
