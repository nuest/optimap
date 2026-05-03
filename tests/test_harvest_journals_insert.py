# SPDX-FileCopyrightText: 2026 OPTIMETA and KOMET projects <https://projects.tib.eu/komet>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests for `python manage.py harvest_journals --insert-sources`."""

from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from works.management.commands.harvest_journals import SOURCE_CONFIG, _is_enabled
from works.models import Source


def _enabled_keys():
    return [k for k, c in SOURCE_CONFIG.items() if _is_enabled(c)]


class InsertSourcesTest(TestCase):
    def test_insert_sources_creates_one_row_per_enabled_journal(self):
        out = StringIO()
        call_command("harvest_journals", "--insert-sources", stdout=out)

        for key in _enabled_keys():
            name = SOURCE_CONFIG[key]["name"]
            self.assertTrue(
                Source.objects.filter(name=name).exists(),
                f"Expected Source for {key} ({name!r}) after --insert-sources",
            )

    def test_insert_sources_is_idempotent(self):
        call_command("harvest_journals", "--insert-sources", stdout=StringIO())
        first_count = Source.objects.count()

        out = StringIO()
        call_command("harvest_journals", "--insert-sources", stdout=out)

        self.assertEqual(Source.objects.count(), first_count)
        self.assertIn("already exists", out.getvalue())

    def test_insert_sources_skips_disabled_by_default(self):
        out = StringIO()
        call_command("harvest_journals", "--insert-sources", stdout=out)

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
            "harvest_journals",
            "--insert-sources",
            "--include-disabled",
            stdout=out,
        )

        for key, config in SOURCE_CONFIG.items():
            self.assertTrue(
                Source.objects.filter(name=config["name"]).exists(),
                f"Source {key} should be inserted with --include-disabled",
            )

    def test_insert_sources_warns_about_non_oai_feeds(self):
        # SOURCE_CONFIG includes RSS (scientific-data) and crossref-prefix (copernicus);
        # the command should warn that the auto-schedule won't work for them.
        out = StringIO()
        call_command(
            "harvest_journals",
            "--insert-sources",
            "--include-disabled",
            stdout=out,
        )
        output = out.getvalue()
        self.assertIn("not OAI-PMH", output)
        # At least one of the non-OAI keys must appear in the warning block.
        non_oai_keys = [
            k for k, c in SOURCE_CONFIG.items()
            if c.get("feed_type", "oai-pmh") != "oai-pmh"
        ]
        self.assertTrue(non_oai_keys, "fixture sanity: SOURCE_CONFIG must have a non-OAI entry")
        self.assertTrue(
            any(k in output for k in non_oai_keys),
            f"Expected one of {non_oai_keys} to be named in the warning, got: {output}",
        )
