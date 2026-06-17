# SPDX-FileCopyrightText: 2026 OPTIMETA and KOMET projects <https://projects.tib.eu/komet>
# SPDX-License-Identifier: GPL-3.0-or-later

"""One-off migration of Works from a deprecated Source to its replacement.

Written for the eScholarship → EarthArXiv consolidation: EarthArXiv preprints
used to be harvested via eScholarship's OAI-PMH endpoint before the journal
moved to its own CDL-backed endpoint (see the "eartharxiv" entry in
harvest_sources.py). The old Source row is still in production with Works
attached to it.

Re-pointing ``Work.source`` is not enough on its own: ``Work.job`` has
``on_delete=CASCADE`` to ``HarvestingEvent``, and ``HarvestingEvent.source``
also cascades from ``Source``. Deleting the old Source after only updating
``Work.source`` would cascade-delete the old Source's HarvestingEvents,
which would in turn cascade-delete every migrated Work still pointing at one
of those events via ``job``. So migrated Works also get detached from their
old ``job`` (set to NULL) before the old Source is removed.

Usage:
    python manage.py migrate_source_works --from-source eScholarship --to-source EarthArXiv --dry-run
    python manage.py migrate_source_works --from-source eScholarship --to-source EarthArXiv
    python manage.py migrate_source_works --from-source eScholarship --to-source EarthArXiv --delete-empty
"""

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from works.models import Source, Work
from works.utils.provenance import append_event


def _resolve_source(token):
    """Look up a Source by numeric id, or by exact/case-insensitive name."""
    if token.isdigit():
        try:
            return Source.objects.get(pk=int(token))
        except Source.DoesNotExist:
            raise CommandError(f"No Source with id={token}") from None

    matches = list(Source.objects.filter(name__iexact=token))
    if not matches:
        raise CommandError(f'No Source with name "{token}" (use the numeric id instead)')
    if len(matches) > 1:
        ids = ", ".join(str(s.pk) for s in matches)
        raise CommandError(f'Multiple Sources named "{token}" (ids: {ids}) — use --from-source/--to-source <id>')
    return matches[0]


class Command(BaseCommand):
    help = (
        "Reassign all Works from one Source to another, then optionally delete "
        "the old Source once it has no Works left."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--from-source",
            required=True,
            help="Deprecated Source — numeric id or exact name (e.g. eScholarship).",
        )
        parser.add_argument(
            "--to-source",
            required=True,
            help="Replacement Source — numeric id or exact name (e.g. EarthArXiv).",
        )
        parser.add_argument(
            "--delete-empty",
            action="store_true",
            help="Delete the old Source after migration if it has zero Works left.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would change without writing anything.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        prefix = "[dry-run] " if dry_run else ""

        old_source = _resolve_source(options["from_source"])
        new_source = _resolve_source(options["to_source"])

        if old_source.pk == new_source.pk:
            raise CommandError("--from-source and --to-source must be different Sources")

        works = Work.objects.filter(source=old_source)
        total = works.count()
        self.stdout.write(
            f'{prefix}Migrating {total} Work(s) from "{old_source.name}" (id={old_source.pk}) '
            f'to "{new_source.name}" (id={new_source.pk})'
        )

        if total == 0:
            self.stdout.write(f"{prefix}Nothing to reassign.")
        elif dry_run:
            for work in works[:20]:
                self.stdout.write(f"{prefix}  would reassign Work id={work.pk} doi={work.doi or work.url}")
            if total > 20:
                self.stdout.write(f"{prefix}  ... and {total - 20} more")
        else:
            with transaction.atomic():
                detached_jobs = 0
                for work in works:
                    work.source = new_source
                    # Detach from the old Source's HarvestingEvent so deleting
                    # that event later (via Source cascade) can't cascade-delete
                    # this Work through Work.job.
                    if work.job_id and work.job.source_id == old_source.pk:
                        work.job = None
                        detached_jobs += 1
                    if old_source.collection_id and old_source.collection_id in work.collections.values_list(
                        "pk", flat=True
                    ):
                        work.collections.remove(old_source.collection_id)
                    if new_source.collection_id:
                        work.collections.add(new_source.collection_id)
                    append_event(
                        work,
                        "source_migration",
                        from_source=old_source.name,
                        to_source=new_source.name,
                    )
                    work.save(update_fields=["source", "job", "provenance"])
                self.stdout.write(
                    self.style.SUCCESS(f"Reassigned {total} Work(s); detached {detached_jobs} from old harvest jobs.")
                )

        if not options["delete_empty"]:
            return

        remaining = Work.objects.filter(source=old_source).count()
        if remaining:
            self.stdout.write(
                self.style.WARNING(f'{prefix}Not deleting "{old_source.name}" — {remaining} Work(s) still attached.')
            )
            return

        if dry_run:
            self.stdout.write(f'{prefix}Would delete Source "{old_source.name}" (id={old_source.pk}).')
            return

        event_count = old_source.harvesting_events.count()
        old_source.delete()
        self.stdout.write(
            self.style.SUCCESS(
                f'Deleted Source "{old_source.name}" (id={old_source.pk}) and its {event_count} HarvestingEvent(s).'
            )
        )
