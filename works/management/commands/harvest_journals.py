# SPDX-FileCopyrightText: 2025 OPTIMETA and KOMET projects <https://projects.tib.eu/komet>
# SPDX-License-Identifier: GPL-3.0-or-later

# publications/management/commands/harvest_journals.py

"""
Django management command to harvest publications from real journal sources.

Supports OAI-PMH, RSS/Atom and (since the Copernicus OAI-PMH endpoint went
404 between Dec 2025 and Apr 2026) Crossref-prefix harvesting. Sources can
be marked ``enabled: False`` to keep their config visible but skip them on
``--all`` runs — useful for documenting upstream outages.

Usage:
    # all currently-enabled sources
    python manage.py harvest_journals --all

    # explicit selection
    python manage.py harvest_journals --journal copernicus --max-records 50
    python manage.py harvest_journals --journal geo-leo --journal eartharxiv

    # narrow a Crossref-prefix source to specific journals
    python manage.py harvest_journals --journal copernicus \
        --journal-title "Earth System Science Data" \
        --journal-title "Atmospheric Chemistry and Physics"
"""

import logging
from django.core.management.base import BaseCommand, CommandError
from django.contrib.auth import get_user_model
from django.utils import timezone
from django.utils.text import slugify
from works.models import Source, HarvestingEvent, Work, Collection
from works.tasks import (
    harvest_oai_endpoint,
    harvest_rss_endpoint,
    harvest_crossref_prefix,
    harvest_mountain_wetlands,
    harvest_openalex_source,
)

logger = logging.getLogger(__name__)
User = get_user_model()

# Source configurations.
#
# `source_type` selects the harvester implementation. When a source has
# `enabled: False` it stays in this config (so the config is the
# documentation) but `--all` skips it with a warning. Use `disabled_reason`
# to explain why for `--list`.
SOURCE_CONFIG = {
    'copernicus': {
        'name': 'Copernicus Publications (Crossref fallback)',
        # The DOI prefix is the source-of-truth filter; the URL is just a
        # display value because the Crossref task builds its own params.
        'url': 'https://api.crossref.org/works?filter=prefix:10.5194',
        'collection_name': 'Copernicus Publications',
        'homepage_url': 'https://publications.copernicus.org/',
        'publisher_name': 'Copernicus Publications',
        'source_type': 'crossref-prefix',
        'crossref_prefix': '10.5194',
        # Default behaviour: fetch the full abstract from the journal
        # landing page rather than the Crossref-supplied <jats:p> render.
        'fetch_abstract_from_publisher': True,
        'is_oa': True,
        'default_work_type': 'article',
    },
    'essd': {
        'name': 'Earth System Science Data',
        'url': 'https://oai-pmh.copernicus.org/oai.php?verb=ListRecords&metadataPrefix=oai_dc&set=essd',
        'collection_name': 'ESSD',
        'homepage_url': 'https://essd.copernicus.org/',
        'publisher_name': 'Copernicus Publications',
        'source_type': 'oai-pmh',
        'is_oa': True,
        'default_work_type': 'dataset',
        # Disabled: oai-pmh.copernicus.org/oai.php has been HTTP 404 since
        # at least Dec 2025 (last Wayback success: 2025-12-15). Use the
        # `copernicus` source above (Crossref prefix 10.5194) to reach the
        # same content while the upstream is dark, and narrow with
        # `--journal-title "Earth System Science Data"` if needed.
        'enabled': False,
        'disabled_reason': (
            'Upstream OAI-PMH endpoint returns HTTP 404 since 2025-12. '
            'Use --journal copernicus --journal-title "Earth System Science Data" instead.'
        ),
    },
    'agile-giss': {
        'name': 'AGILE-GISS',
        'url': 'https://oai-pmh.copernicus.org/oai.php?verb=ListRecords&metadataPrefix=oai_dc&set=agile-giss',
        'collection_name': 'AGILE-GISS',
        'homepage_url': 'https://www.agile-giscience-series.net/',
        'publisher_name': 'Copernicus Publications',
        'source_type': 'oai-pmh',
        'is_oa': True,
        'default_work_type': 'proceedings-article',
        'enabled': False,
        'disabled_reason': (
            'Upstream OAI-PMH endpoint returns HTTP 404 since 2025-12. '
            'Use agile-giss-crossref or agile-giss-openalex instead.'
        ),
    },
    'agile-giss-crossref': {
        'name': 'AGILE: GIScience Series (Crossref)',
        # Crossref-prefix harvester ignores `url` (builds its own params), but
        # we keep a representative URL for the admin UI / --list display.
        'url': 'https://api.crossref.org/works?filter=prefix:10.5194,container-title:AGILE%3A+GIScience+Series',
        'collection_name': 'AGILE-GISS',
        'homepage_url': 'https://www.agile-giscience-series.net/articles/index.html',
        'publisher_name': 'Copernicus Publications',
        'source_type': 'crossref-prefix',
        'crossref_prefix': '10.5194',
        # Baked-in container-title filter so an --all run reaches AGILE-GISS
        # without the operator having to remember the title string. Note the
        # colon: Crossref records the title as 'AGILE: GIScience Series'
        # (verified 2026-05-06); without the colon the filter returns zero hits.
        'journal_titles': ['AGILE: GIScience Series'],
        'fetch_abstract_from_publisher': True,
        'is_oa': True,
        'default_work_type': 'proceedings-article',
    },
    'agile-giss-openalex': {
        'name': 'AGILE GIScience Series (OpenAlex)',
        # The harvester resolves S<digits> from openalex_id (preferred) or
        # url_field (fallback). The public Source API derives the display URL
        # from openalex_id on the fly.
        'url': 'https://api.openalex.org/sources/S4210203054',
        'collection_name': 'AGILE-GISS',
        'homepage_url': 'https://www.agile-giscience-series.net/articles/index.html',
        'publisher_name': 'Copernicus Publications',
        'source_type': 'openalex',
        'openalex_id': 'S4210203054',
        'is_oa': True,
        'default_work_type': 'proceedings-article',
    },
    'geo-leo': {
        'name': 'GEO-LEO e-docs',
        'url': 'https://e-docs.geo-leo.de/server/oai/request?verb=ListRecords&metadataPrefix=oai_dc',
        'collection_name': 'GEO-LEO',
        'homepage_url': 'https://e-docs.geo-leo.de/',
        'publisher_name': 'GEO-LEO',
        'source_type': 'oai-pmh',
        'is_oa': True,
        'default_work_type': 'article',
    },
    'eartharxiv': {
        'name': 'EarthArXiv',
        'url': 'https://eartharxiv.org/api/oai/?verb=ListRecords&metadataPrefix=oai_dc',
        'collection_name': 'EarthArXiv',
        'homepage_url': 'https://eartharxiv.org/',
        'publisher_name': 'California Digital Library',
        'source_type': 'oai-pmh',
        'is_oa': True,
        'is_preprint': True,
        'default_work_type': 'preprint',
    },
    'scientific-data': {
        'name': 'Scientific Data',
        'url': 'https://www.nature.com/sdata.rss',
        'collection_name': 'Scientific Data',
        'homepage_url': 'https://www.nature.com/sdata/',
        'publisher_name': 'Nature Publishing Group',
        'source_type': 'rss',
        'is_oa': True,
        'default_work_type': 'dataset',
    },
    'mountain-wetlands': {
        'name': 'Mountain Wetlands Repository',
        'url': 'https://andes.mountain-wetlands-repository.info/api/v1/items/',
        'collection_name': 'Mountain Wetlands',
        'homepage_url': 'https://andes.mountain-wetlands-repository.info/',
        'publisher_name': 'Mountain Wetlands Repository (MaRESS)',
        'source_type': 'mountain-wetlands',
        'is_oa': True,
        'default_work_type': 'article',
    },
}


def _is_enabled(config):
    """Sources without an `enabled` key default to True for back-compat."""
    return config.get('enabled', True)


def _get_or_create_collection(config):
    """Return the Collection matching ``config['collection_name']``, creating it on first use."""
    name = config.get('collection_name')
    if not name:
        return None
    identifier = slugify(name)[:100] or 'collection'
    collection, _ = Collection.objects.get_or_create(
        identifier=identifier,
        defaults={
            'name': name,
            'description': '',
            'homepage_url': config.get('homepage_url') or None,
            'is_published': True,
        },
    )
    return collection


class Command(BaseCommand):
    help = 'Harvest publications from real journal sources into the current database'

    def add_arguments(self, parser):
        parser.add_argument(
            '--journal',
            action='append',
            choices=list(SOURCE_CONFIG.keys()),
            help=(
                f'Journal to harvest (choices: {", ".join(SOURCE_CONFIG.keys())}). '
                'Can be specified multiple times.'
            ),
        )
        parser.add_argument(
            '--journal-title',
            action='append',
            default=None,
            help=(
                'For Crossref-prefix sources, narrow the harvest to specific '
                'container-title strings. Repeat the flag for multiple titles. '
                'Ignored for OAI-PMH and RSS sources.'
            ),
        )
        parser.add_argument(
            '--all',
            action='store_true',
            help='Harvest from all enabled journals (skips entries marked enabled: False)',
        )
        parser.add_argument(
            '--include-disabled',
            action='store_true',
            help='When combined with --all, also attempt disabled sources (rarely useful — disabled means upstream is broken)',
        )
        parser.add_argument(
            '--max-records',
            type=int,
            default=None,
            help='Maximum number of records to harvest per journal (default: unlimited)',
        )
        parser.add_argument(
            '--update',
            action='store_true',
            help=(
                'Update same-source duplicates in place instead of skipping '
                'them. Geometry and temporal metadata on the existing Work are '
                'preserved if the new harvest brings nothing for those fields '
                "(typically because they were contributed by users via "
                'OPTIMAP, not the source). Status and created_by are never '
                'overwritten. A "harvest_update" event is appended to '
                'Work.provenance.events.'
            ),
        )
        parser.add_argument(
            '--no-publisher-abstract',
            action='store_true',
            help=(
                'For Crossref-prefix sources, skip the publisher-side '
                'landing-page fetch and use the Crossref-supplied abstract '
                'as-is (faster, but loses formatting and is sometimes '
                'incomplete). Default: fetch the canonical abstract from '
                'the publisher.'
            ),
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
        parser.add_argument(
            '--insert-sources',
            action='store_true',
            help=(
                'Insert all journals from SOURCE_CONFIG as Source rows (so they '
                'show up in the Django admin and can be triggered from there) '
                'and exit without harvesting. Existing rows (matched by name or '
                'URL) are left untouched. Disabled journals are skipped unless '
                '--include-disabled is also given.'
            ),
        )

    def handle(self, *args, **options):
        # List journals and exit
        if options['list']:
            self.stdout.write(self.style.SUCCESS('\nAvailable journals for harvesting:\n'))
            for key, config in SOURCE_CONFIG.items():
                source_type = config.get('source_type', 'oai-pmh').upper()
                is_preprint = ' (preprint)' if config.get('is_preprint', False) else ''
                work_type = config.get('default_work_type', 'article')
                marker = '' if _is_enabled(config) else ' [DISABLED]'
                self.stdout.write(f"  {key:15} - {config['name']}{is_preprint}{marker}")
                self.stdout.write(
                    f"                  Type: {source_type}, Work Type: {work_type}, URL: {config['homepage_url']}"
                )
                if not _is_enabled(config) and config.get('disabled_reason'):
                    self.stdout.write(
                        self.style.WARNING(
                            f"                  Reason: {config['disabled_reason']}"
                        )
                    )
            return

        include_disabled = options['include_disabled']
        journal_titles = options['journal_title']
        no_publisher_abstract = options['no_publisher_abstract']

        # Bulk-insert sources and exit (no harvesting)
        if options['insert_sources']:
            self._insert_sources(include_disabled=include_disabled)
            return

        # Determine which journals to harvest
        if options['all']:
            if include_disabled:
                journals_to_harvest = list(SOURCE_CONFIG.keys())
            else:
                journals_to_harvest = [
                    k for k, c in SOURCE_CONFIG.items() if _is_enabled(c)
                ]
        elif options['journal']:
            journals_to_harvest = options['journal']
        else:
            raise CommandError(
                'Please specify --all to harvest all enabled journals, or '
                '--journal <name> for specific journals.\n'
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
        update_existing = options.get('update', False)

        # Summary statistics
        total_harvested = 0
        total_failed = 0
        total_skipped = 0
        results = []

        self.stdout.write(self.style.SUCCESS(f'\n{"="*70}'))
        self.stdout.write(self.style.SUCCESS(f'Starting harvest of {len(journals_to_harvest)} journal(s)'))
        self.stdout.write(self.style.SUCCESS(f'{"="*70}\n'))

        # Harvest each journal
        for journal_key in journals_to_harvest:
            config = SOURCE_CONFIG[journal_key]

            # Skip explicitly-disabled sources unless the operator opted in.
            if not _is_enabled(config) and not include_disabled:
                self.stdout.write(self.style.WARNING(
                    f'\n--- Skipping disabled source: {config["name"]} ---'
                ))
                if config.get('disabled_reason'):
                    self.stdout.write(f'  Reason: {config["disabled_reason"]}')
                total_skipped += 1
                results.append({
                    'journal': config['name'],
                    'status': 'skipped',
                    'count': 0,
                })
                continue

            self.stdout.write(self.style.WARNING(f'\n--- Harvesting: {config["name"]} ---'))
            self.stdout.write(f'URL: {config["url"]}')
            if max_records:
                self.stdout.write(f'Max records: {max_records}')

            try:
                # Find or create source
                source = self._get_or_create_source(config, create_sources)

                # Harvest based on source type
                harvest_start = timezone.now()
                source_type = config.get('source_type', 'oai-pmh')

                if update_existing:
                    self.stdout.write(
                        '  --update: same-source duplicates will be updated in place '
                        '(geometry/temporal preserved when new harvest is empty).'
                    )

                if source_type == 'rss':
                    self.stdout.write('Source type: RSS/Atom')
                    harvest_rss_endpoint(
                        source.id, user=user, max_records=max_records,
                        update_existing=update_existing,
                    )
                elif source_type == 'mountain-wetlands':
                    self.stdout.write('Source type: Mountain Wetlands Repository (MaRESS)')
                    harvest_mountain_wetlands(
                        source.id, user=user, max_records=max_records,
                        update_existing=update_existing,
                    )
                elif source_type == 'crossref-prefix':
                    self.stdout.write('Source type: Crossref by DOI prefix')
                    # CLI --journal-title takes precedence; otherwise fall back
                    # to titles baked into the config (e.g. agile-giss-crossref).
                    effective_titles = journal_titles or config.get('journal_titles')
                    if effective_titles:
                        self.stdout.write(
                            f'  Filtering to titles: {", ".join(effective_titles)}'
                        )
                    fetch_abstract = (
                        config.get('fetch_abstract_from_publisher', True)
                        and not no_publisher_abstract
                    )
                    self.stdout.write(
                        f'  Fetch abstract from publisher landing page: '
                        f'{"yes" if fetch_abstract else "no"}'
                    )
                    harvest_crossref_prefix(
                        source.id,
                        user=user,
                        max_records=max_records,
                        journal_titles=effective_titles,
                        prefix=config.get('crossref_prefix'),
                        fetch_abstract_from_publisher=fetch_abstract,
                        update_existing=update_existing,
                    )
                elif source_type == 'openalex':
                    self.stdout.write('Source type: OpenAlex source')
                    self.stdout.write(
                        f'  OpenAlex source ID: {config.get("openalex_id", "<from source row>")}'
                    )
                    harvest_openalex_source(
                        source.id,
                        user=user,
                        max_records=max_records,
                        update_existing=update_existing,
                    )
                else:
                    # Covers source_type in {oai-pmh, ojs, janeway} — all share the OAI harvester.
                    self.stdout.write(f'Source type: {source_type}')
                    harvest_oai_endpoint(
                        source.id, user=user, max_records=max_records,
                        update_existing=update_existing,
                    )

                # Get results
                event = HarvestingEvent.objects.filter(source=source).latest('started_at')
                pub_count = Work.objects.filter(job=event).count()

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
                spatial_count = Work.objects.filter(
                    job=event
                ).exclude(geometry__isnull=True).count()

                temporal_count = Work.objects.filter(
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
            if result['status'] == 'success':
                symbol, style = '✓', self.style.SUCCESS
                self.stdout.write(style(
                    f"{symbol} {result['journal']:30} {result['count']:5} publications "
                    f"({result['duration']:.1f}s)"
                ))
            elif result['status'] == 'skipped':
                self.stdout.write(self.style.WARNING(
                    f"⊘ {result['journal']:30} skipped (disabled)"
                ))
            else:
                error_msg = result.get('error', result['status'])
                self.stdout.write(self.style.ERROR(
                    f"✗ {result['journal']:30} Failed: {error_msg}"
                ))

        self.stdout.write(f'\nTotal publications harvested: {total_harvested}')
        if total_failed > 0:
            self.stdout.write(self.style.WARNING(f'Failed journals: {total_failed}'))
        if total_skipped > 0:
            self.stdout.write(self.style.WARNING(
                f'Skipped (disabled) journals: {total_skipped}. '
                'Use --include-disabled to attempt them anyway.'
            ))

        self.stdout.write(self.style.SUCCESS(f'\n{"="*70}\n'))

    def _insert_sources(self, include_disabled=False):
        """Create Source rows for every entry in SOURCE_CONFIG without harvesting.

        Existing rows (matched by name or URL) are reported and left untouched.
        Note: Source.save() always schedules harvest_oai_endpoint, so RSS and
        Crossref-prefix sources still need the --journal CLI route to harvest
        correctly — they will appear in the admin but the auto-schedule will
        not work for them until the dispatch logic is generalised.
        """
        self.stdout.write(self.style.SUCCESS(f'\n{"="*70}'))
        self.stdout.write(self.style.SUCCESS('Inserting journal sources into the database'))
        self.stdout.write(self.style.SUCCESS(f'{"="*70}\n'))

        created = 0
        existed = 0
        skipped = 0
        non_oai = []

        for key, config in SOURCE_CONFIG.items():
            if not _is_enabled(config) and not include_disabled:
                self.stdout.write(self.style.WARNING(
                    f"⊘ {key:15} skipped (disabled — pass --include-disabled to insert)"
                ))
                if config.get('disabled_reason'):
                    self.stdout.write(f"                  Reason: {config['disabled_reason']}")
                skipped += 1
                continue

            existing = (
                Source.objects.filter(name=config['name']).first()
                or Source.objects.filter(url_field=config['url']).first()
            )
            if existing:
                self.stdout.write(
                    f"= {key:15} already exists (id={existing.id}, name={existing.name!r})"
                )
                self._reconcile_source(existing, config)
                existed += 1
                continue

            source = Source.objects.create(
                name=config['name'],
                url_field=config['url'],
                source_type=config.get('source_type', 'oai-pmh'),
                collection=_get_or_create_collection(config),
                homepage_url=config.get('homepage_url'),
                publisher_name=config.get('publisher_name'),
                is_oa=config.get('is_oa', False),
                is_preprint=config.get('is_preprint', False),
                default_work_type=config.get('default_work_type', 'article'),
                openalex_id=config.get('openalex_id'),
                harvest_interval_minutes=0,
            )
            self.stdout.write(self.style.SUCCESS(
                f"+ {key:15} created (id={source.id}, name={source.name!r})"
            ))
            created += 1
            if config.get('source_type', 'oai-pmh') != 'oai-pmh':
                non_oai.append((key, config['source_type']))

        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS(
            f'Done. Created: {created}, already existed: {existed}, skipped: {skipped}.'
        ))
        if non_oai:
            self.stdout.write(
                '\nNote: the following inserted sources use non-OAI source types '
                '(Source.save() dispatches to the correct task per source_type, '
                'and harvest_interval_minutes defaults to 0 so they are not auto-scheduled — '
                'run them via this management command):'
            )
            for key, source_type in non_oai:
                self.stdout.write(f"  - {key} ({source_type})")
        self.stdout.write(self.style.SUCCESS(f'\n{"="*70}\n'))

    def _get_or_create_source(self, config, create_if_missing):
        """Get or optionally create a Source for the journal."""
        source = Source.objects.filter(name=config['name']).first()

        if not source:
            source = Source.objects.filter(url_field=config['url']).first()

        if source:
            self.stdout.write(f'Using existing source: {source.name} (ID: {source.id})')
            self._reconcile_source(source, config)
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
            source_type=config.get('source_type', 'oai-pmh'),
            collection=_get_or_create_collection(config),
            homepage_url=config.get('homepage_url'),
            publisher_name=config.get('publisher_name'),
            is_oa=config.get('is_oa', False),
            is_preprint=config.get('is_preprint', False),
            default_work_type=config.get('default_work_type', 'article'),
            openalex_id=config.get('openalex_id'),
            harvest_interval_minutes=0,
        )

        self.stdout.write(self.style.SUCCESS(
            f'Created new source: {source.name} (ID: {source.id})'
        ))

        return source

    def _reconcile_source(self, source, config):
        """Reconcile an existing Source row with its SOURCE_CONFIG entry.

        ``source_type`` is rewritten from the config; the other config-derived
        fields are filled only when blank so admin edits are preserved.
        """
        update_fields = []

        config_type = config.get('source_type', 'oai-pmh')
        if source.source_type != config_type:
            self.stdout.write(self.style.WARNING(
                f"  Reconciled source_type: {source.source_type!r} -> {config_type!r}"
            ))
            source.source_type = config_type
            update_fields.append('source_type')

        if not source.collection_id:
            col = _get_or_create_collection(config)
            if col is not None:
                self.stdout.write(f"  Linked to collection: {col.name}")
                source.collection = col
                update_fields.append('collection')

        for field in ('homepage_url', 'publisher_name', 'default_work_type', 'openalex_id'):
            new_value = config.get(field)
            if not new_value or getattr(source, field):
                continue
            self.stdout.write(f"  Filled blank {field}: {new_value!r}")
            setattr(source, field, new_value)
            update_fields.append(field)

        if update_fields:
            source.save(update_fields=update_fields)
        return source
