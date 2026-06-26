# SPDX-FileCopyrightText: 2026 OPTIMETA and KOMET projects <https://projects.tib.eu/komet>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests for `python manage.py harvest_sources --insert-sources`."""

from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from works.management.commands.harvest_sources import SOURCE_CONFIG, _is_enabled
from works.models import Collection, Source


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

        disabled = [k for k, c in SOURCE_CONFIG.items() if not _is_enabled(c)]
        for key in disabled:
            self.assertFalse(
                Source.objects.filter(name=SOURCE_CONFIG[key]["name"]).exists(),
                f"Disabled source {key} should not be inserted by default",
            )
        # The skip message only appears when at least one source is disabled.
        if disabled:
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
        cfg = SOURCE_CONFIG["mountain-wetlands"]
        broken = Source.objects.create(
            name=cfg["name"],
            url_field=cfg["url"],
            source_type="oai-pmh",
        )
        self.assertEqual(broken.source_type, "oai-pmh")

        out = StringIO()
        call_command("harvest_sources", "--insert-sources", stdout=out)

        broken.refresh_from_db()
        self.assertEqual(broken.source_type, "mountain-wetlands")
        self.assertIn("Reconciled source_type", out.getvalue())

    def test_insert_sources_does_not_clobber_admin_set_homepage_url(self):
        cfg = SOURCE_CONFIG["mountain-wetlands"]
        admin_chosen_url = "https://admin-edited.example.org/"
        existing = Source.objects.create(
            name=cfg["name"],
            url_field=cfg["url"],
            source_type="mountain-wetlands",
            homepage_url=admin_chosen_url,
        )

        call_command("harvest_sources", "--insert-sources", stdout=StringIO())

        existing.refresh_from_db()
        self.assertEqual(existing.homepage_url, admin_chosen_url)

    def test_insert_sources_fills_blank_collection_on_existing_row(self):
        cfg = SOURCE_CONFIG["mountain-wetlands"]
        existing = Source.objects.create(
            name=cfg["name"],
            url_field=cfg["url"],
            source_type="mountain-wetlands",
            collection=None,
        )
        self.assertIsNone(existing.collection)

        call_command("harvest_sources", "--insert-sources", stdout=StringIO())

        existing.refresh_from_db()
        self.assertIsNotNone(existing.collection)
        self.assertEqual(existing.collection.name, cfg["collection_name"])

    def test_insert_sources_creates_collections_unpublished(self):
        # The plain-deployment update process (etc/deploy-plain/update-app.sh)
        # runs `--insert-sources` on every update, and on a fresh database that
        # (re-)creates every built-in collection. New collections must start
        # unpublished so they are not exposed to anonymous users / sitemaps
        # before an operator reviews and publishes them explicitly.
        call_command("harvest_sources", "--insert-sources", "--include-disabled", stdout=StringIO())

        published = Collection.objects.filter(is_published=True)
        self.assertFalse(
            published.exists(),
            f"--insert-sources must not auto-publish collections; published: {list(published)}",
        )

    def test_insert_sources_preserves_collection_publish_status(self):
        # Regression guard for the plain-deployment update process: a collection
        # an operator has published must stay published across re-runs, and an
        # unpublished one must stay unpublished. is_published lives in
        # get_or_create's `defaults`, so it is only applied at creation — never
        # on subsequent runs.
        call_command("harvest_sources", "--insert-sources", stdout=StringIO())

        # Collections are created unpublished; an operator publishes one.
        cfg = SOURCE_CONFIG["mountain-wetlands"]
        collection = Collection.objects.get(name=cfg["collection_name"])
        self.assertFalse(collection.is_published)
        collection.is_published = True
        collection.save(update_fields=["is_published"])

        # A later deployment re-runs the insert step.
        call_command("harvest_sources", "--insert-sources", stdout=StringIO())

        collection.refresh_from_db()
        self.assertTrue(
            collection.is_published,
            "Operator-published collection must survive a deployment --insert-sources re-run",
        )

        # And the inverse: an admin re-unpublishing it is also preserved.
        collection.is_published = False
        collection.save(update_fields=["is_published"])
        call_command("harvest_sources", "--insert-sources", stdout=StringIO())
        collection.refresh_from_db()
        self.assertFalse(collection.is_published)

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
        non_oai_keys = [k for k, c in SOURCE_CONFIG.items() if c.get("source_type", "oai-pmh") != "oai-pmh"]
        self.assertTrue(non_oai_keys, "fixture sanity: SOURCE_CONFIG must have a non-OAI entry")
        self.assertTrue(
            any(k in output for k in non_oai_keys),
            f"Expected one of {non_oai_keys} to be named in the warning, got: {output}",
        )
