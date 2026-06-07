# SPDX-FileCopyrightText: 2026 OPTIMETA and KOMET projects <https://projects.tib.eu/komet>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests for `python manage.py harvest_sources --insert-sources`."""

from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from works.management.commands.harvest_sources import SOURCE_CONFIG, _is_enabled
from works.models import Source


def _enabled_keys():
    return [k for k, c in SOURCE_CONFIG.items() if _is_enabled(c)]


class InsertSourcesTest(TestCase):
    def test_insert_sources_creates_one_row_per_enabled_source(self):
        out = StringIO()
        call_command("harvest_sources", "--insert-sources", stdout=out)

        for key in _enabled_keys():
            name = SOURCE_CONFIG[key]["name"]
            self.assertTrue(
                Source.objects.filter(name=name).exists(),
                f"Expected Source for {key} ({name!r}) after --insert-sources",
            )

    def test_insert_sources_is_idempotent(self):
        call_command("harvest_sources", "--insert-sources", stdout=StringIO())
        first_count = Source.objects.count()

        out = StringIO()
        call_command("harvest_sources", "--insert-sources", stdout=out)

        self.assertEqual(Source.objects.count(), first_count)
        self.assertIn("already exists", out.getvalue())

    def test_insert_sources_skips_disabled_by_default(self):
        out = StringIO()
        call_command("harvest_sources", "--insert-sources", stdout=out)

        for key, config in SOURCE_CONFIG.items():
            if _is_enabled(config):
                continue
            self.assertFalse(
                Source.objects.filter(name=config["name"]).exists(),
                f"Disabled source {key} should not be inserted by default",
            )
        self.assertIn("skipped (disabled", out.getvalue())

    def test_insert_sources_with_include_disabled_inserts_everything(self):
        out = StringIO()
        call_command(
            "harvest_sources",
            "--insert-sources",
            "--include-disabled",
            stdout=out,
        )

        for key, config in SOURCE_CONFIG.items():
            self.assertTrue(
                Source.objects.filter(name=config["name"]).exists(),
                f"Source {key} should be inserted with --include-disabled",
            )

    def test_insert_sources_reconciles_wrong_source_type_on_existing_row(self):
        cfg = SOURCE_CONFIG['mountain-wetlands']
        broken = Source.objects.create(
            name=cfg['name'], url_field=cfg['url'],
            source_type='oai-pmh',
        )
        self.assertEqual(broken.source_type, 'oai-pmh')

        out = StringIO()
        call_command("harvest_sources", "--insert-sources", stdout=out)

        broken.refresh_from_db()
        self.assertEqual(broken.source_type, 'mountain-wetlands')
        self.assertIn('Reconciled source_type', out.getvalue())

    def test_insert_sources_does_not_clobber_admin_set_homepage_url(self):
        cfg = SOURCE_CONFIG['mountain-wetlands']
        admin_chosen_url = 'https://admin-edited.example.org/'
        existing = Source.objects.create(
            name=cfg['name'], url_field=cfg['url'],
            source_type='mountain-wetlands',
            homepage_url=admin_chosen_url,
        )

        call_command("harvest_sources", "--insert-sources", stdout=StringIO())

        existing.refresh_from_db()
        self.assertEqual(existing.homepage_url, admin_chosen_url)

    def test_insert_sources_fills_blank_collection_on_existing_row(self):
        cfg = SOURCE_CONFIG['mountain-wetlands']
        existing = Source.objects.create(
            name=cfg['name'], url_field=cfg['url'],
            source_type='mountain-wetlands',
            collection=None,
        )
        self.assertIsNone(existing.collection)

        call_command("harvest_sources", "--insert-sources", stdout=StringIO())

        existing.refresh_from_db()
        self.assertIsNotNone(existing.collection)
        self.assertEqual(existing.collection.name, cfg['collection_name'])

    def test_insert_sources_warns_about_non_oai_feeds(self):
        # SOURCE_CONFIG includes RSS (scientific-data) and crossref-prefix (copernicus);
        # the command should warn that the auto-schedule won't work for them.
        out = StringIO()
        call_command(
            "harvest_sources",
            "--insert-sources",
            "--include-disabled",
            stdout=out,
        )
        output = out.getvalue()
        self.assertIn("non-OAI source types", output)
        # At least one of the non-OAI keys must appear in the warning block.
        non_oai_keys = [
            k for k, c in SOURCE_CONFIG.items()
            if c.get("source_type", "oai-pmh") != "oai-pmh"
        ]
        self.assertTrue(non_oai_keys, "fixture sanity: SOURCE_CONFIG must have a non-OAI entry")
        self.assertTrue(
            any(k in output for k in non_oai_keys),
            f"Expected one of {non_oai_keys} to be named in the warning, got: {output}",
        )
