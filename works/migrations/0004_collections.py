# SPDX-FileCopyrightText: 2026 OPTIMETA and KOMET projects
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Introduces the Collection model and replumbs Source/Work for it:
#   - new Collection model (identifier, short_slug, name, description,
#     homepage_url, is_published, curators M2M, timestamps)
#   - Work.collection FK
#   - Work.provenance: TextField → JSONField (legacy text preserved under
#     {"text_log": "..."})
#   - Source.source_type choice field (oai-pmh / ojs / janeway / rss /
#     crossref-prefix / mountain-wetlands), classified for existing rows
#     by URL heuristic
#   - Source.harvest_interval_minutes default flips 60*24*3 → 0
#     (manual-only by default for new sources; existing intervals
#     preserved)
#   - Source.collection FK + drop of legacy collection_name string field
#     (one Collection per distinct existing collection_name)
#   - orphan Django-Q schedules wiped (the old save() created schedules
#     for every Source pointed at harvest_oai_endpoint regardless of
#     source type; this migration clears them so save() can re-create
#     correct ones on the next admin save)

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
from django.utils.text import slugify


def _classify_source_type(url, name):
    """Best-effort URL-pattern heuristic. Admins can reclassify in admin."""
    u = (url or '').lower()
    if 'crossref' in u:
        return 'crossref-prefix'
    if u.endswith('.rss') or '/rss' in u or u.endswith('.xml') and 'oai' not in u:
        return 'rss'
    if '/api/oai' in u:
        return 'janeway'
    if '/index.php/' in u and '/oai' in u:
        return 'ojs'
    return 'oai-pmh'


def _migrate_data(apps, schema_editor):
    Source = apps.get_model('works', 'Source')
    Work = apps.get_model('works', 'Work')
    Collection = apps.get_model('works', 'Collection')

    # 1. Classify source_type for every existing Source.
    for source in Source.objects.all():
        source.source_type = _classify_source_type(source.url_field, source.name)
        source.save(update_fields=['source_type'])

    # 2. Create one Collection per distinct non-empty collection_name.
    name_to_collection = {}
    for name in Source.objects.exclude(collection_name__isnull=True).exclude(
        collection_name__exact=''
    ).values_list('collection_name', flat=True).distinct():
        identifier = slugify(name)[:100] or 'collection'
        # Guard against slug collisions (e.g. names that slugify to the same value).
        base = identifier
        suffix = 2
        while Collection.objects.filter(identifier=identifier).exists():
            identifier = f"{base}-{suffix}"[:100]
            suffix += 1
        col = Collection.objects.create(
            identifier=identifier,
            name=name,
            description='',
            is_published=True,  # pre-existing collections were already user-facing
        )
        name_to_collection[name] = col

    # 3. Link Source.collection FK and propagate to existing Works via the M2M.
    for source in Source.objects.exclude(collection_name__isnull=True).exclude(
        collection_name__exact=''
    ):
        col = name_to_collection.get(source.collection_name)
        if col is None:
            continue
        source.collection_id = col.id
        source.save(update_fields=['collection'])
        # Add the collection to every existing Work harvested from this source.
        # bulk_create on the auto-generated through table is the cheap way:
        # one INSERT per (work, collection) pair, no instance overhead.
        Through = Work.collections.through
        existing_pairs = set(
            Through.objects.filter(collection_id=col.id).values_list('work_id', flat=True)
        )
        new_links = [
            Through(work_id=wid, collection_id=col.id)
            for wid in Work.objects.filter(source_id=source.id).values_list('id', flat=True)
            if wid not in existing_pairs
        ]
        if new_links:
            Through.objects.bulk_create(new_links)

    # 4. Convert legacy text provenance into the structured JSON shape so
    #    existing landing pages still render something useful. We don't
    #    try to parse the old freeform strings — we just stash them under
    #    "text_log" so the new template tag can render them verbatim.
    for work in Work.objects.exclude(provenance_legacy__isnull=True).exclude(
        provenance_legacy__exact=''
    ).only('id', 'provenance_legacy'):
        Work.objects.filter(pk=work.pk).update(
            provenance={'text_log': work.provenance_legacy},
        )

    # 5. Wipe orphan/wrong-task Django-Q schedules. The old Source.save()
    #    created `Harvest Source <id>` schedules pointed at
    #    harvest_oai_endpoint for every Source — wrong for RSS/Crossref
    #    sources. Source.save() will re-create the correct schedule on
    #    next admin save when interval > 0.
    Schedule = apps.get_model('django_q', 'Schedule')
    Schedule.objects.filter(name__startswith='Harvest Source ').delete()


def _reverse_data(apps, schema_editor):
    # No reverse: dropping the Collection model on rollback also drops
    # the FKs, so nothing useful to do here. Restoring legacy text
    # provenance would be lossy.
    pass


class Migration(migrations.Migration):

    # Non-atomic: the data migration step writes FK rows whose deferred-FK
    # triggers prevent the subsequent RemoveField ALTER TABLE statements
    # from running in the same transaction (Postgres "pending trigger
    # events"). Each operation runs in its own transaction instead.
    atomic = False

    dependencies = [
        ('works', '0003_harvestingevent_error_message_and_more'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        # Schema: new Collection model.
        migrations.CreateModel(
            name='Collection',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('identifier', models.SlugField(
                    max_length=100, unique=True,
                    help_text='URL-safe identifier (e.g. "mountain-wetlands"). Used in /collections/<identifier>/.',
                )),
                ('short_slug', models.SlugField(
                    max_length=100, unique=True, null=True, blank=True,
                    help_text='Optional vanity URL slug. If set, /<short_slug>/ 301-redirects to /collections/<identifier>/.',
                )),
                ('name', models.CharField(max_length=255)),
                ('description', models.TextField(blank=True, default='')),
                ('homepage_url', models.URLField(blank=True, max_length=512, null=True)),
                ('is_published', models.BooleanField(
                    default=False,
                    help_text='Only published collections are visible to anonymous users and listed in sitemaps.',
                )),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('curators', models.ManyToManyField(
                    blank=True, related_name='curated_collections', to=settings.AUTH_USER_MODEL,
                    help_text='Users who can add/remove works to/from this collection from the work landing page.',
                )),
            ],
            options={'ordering': ['name']},
        ),

        # Schema: Work.collections M2M + provenance rename → JSONField.
        # M2M (not FK): a work can belong to multiple curated collections —
        # e.g. a single AGILE paper that's also part of a thematic set.
        migrations.AddField(
            model_name='work',
            name='collections',
            field=models.ManyToManyField(
                blank=True,
                related_name='works', to='works.collection',
                help_text='Curated collections this work belongs to (e.g. mountain-wetlands, agile-gi). A work can belong to multiple collections.',
            ),
        ),
        migrations.RenameField(
            model_name='work',
            old_name='provenance',
            new_name='provenance_legacy',
        ),
        migrations.AddField(
            model_name='work',
            name='provenance',
            field=models.JSONField(
                blank=True, default=dict,
                help_text='Structured provenance: harvest details, per-field metadata sources, OpenAlex match, contribution/publish events.',
            ),
        ),

        # Schema: Source.source_type + collection FK + interval default.
        migrations.AddField(
            model_name='source',
            name='source_type',
            field=models.CharField(
                choices=[
                    ('oai-pmh', 'OAI-PMH (generic)'),
                    ('ojs', 'OJS (Open Journal Systems)'),
                    ('janeway', 'Janeway'),
                    ('rss', 'RSS / Atom feed'),
                    ('crossref-prefix', 'Crossref (DOI prefix)'),
                    ('mountain-wetlands', 'Mountain Wetlands Repository'),
                ],
                default='oai-pmh', db_index=True, max_length=32,
                help_text='Platform / API style of this source. Selects which harvester runs.',
            ),
        ),
        migrations.AddField(
            model_name='source',
            name='collection',
            field=models.ForeignKey(
                blank=True, null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='sources', to='works.collection',
                help_text='Default collection assigned to works harvested from this source.',
            ),
        ),
        migrations.AlterField(
            model_name='source',
            name='harvest_interval_minutes',
            field=models.IntegerField(
                default=0,
                help_text='Auto-harvest interval in minutes. 0 means manual-only (run via management command or admin action).',
            ),
        ),

        # Data: backfill source_type, create Collections from collection_name,
        # link Source/Work to Collection, parse legacy provenance text,
        # wipe orphan Django-Q schedules.
        migrations.RunPython(_migrate_data, _reverse_data),

        # Schema: drop legacy fields now that data has moved.
        migrations.RemoveField(model_name='source', name='collection_name'),
        migrations.RemoveField(model_name='work', name='provenance_legacy'),
    ]
