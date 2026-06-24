# SPDX-FileCopyrightText: 2026 OPTIMETA and KOMET projects <https://projects.tib.eu/komet>
# SPDX-License-Identifier: GPL-3.0-or-later

from django.db import migrations, models

# Dropping works_work.country_code with CASCADE also drops the works_published
# view (defined as SELECT * in migration 0011, so it depends on every column).
# Recreate it afterwards, now exposing an aggregated `country_codes` text column
# (comma-separated ISO 3166-1 alpha-2) sourced from the new Work.countries M2M,
# so the pygeoapi /ogcapi/ feature provider keeps working.
_CREATE_VIEW = """
CREATE OR REPLACE VIEW works_published AS
    SELECT w.*,
           (SELECT string_agg(c.iso_code, ',' ORDER BY c.iso_code)
              FROM works_work_countries wc
              JOIN works_country c ON c.id = wc.country_id
             WHERE wc.work_id = w.id) AS country_codes
      FROM works_work w
     WHERE w.status = 'p';
"""

# Reverse: restore the pre-#261 view (plain SELECT *, which again includes the
# country_code column re-added by reversing RemoveField).
_CREATE_VIEW_LEGACY = """
CREATE OR REPLACE VIEW works_published AS
    SELECT * FROM works_work WHERE status = 'p';
"""

_DROP_VIEW = "DROP VIEW IF EXISTS works_published;"


def link_existing_country_codes(apps, schema_editor):
    """Preserve single-country data: link each work's ``country_code`` to the
    matching ``Country`` (by ``iso_code``) before the scalar column is dropped.

    No-ops gracefully when the ``Country`` table is empty (``load_countries``
    not yet run) or a code has no matching row.
    """
    Work = apps.get_model("works", "Work")
    Country = apps.get_model("works", "Country")
    by_code = {c.iso_code: c for c in Country.objects.all()}
    if not by_code:
        return
    for work in Work.objects.exclude(country_code__isnull=True).exclude(country_code="").iterator():
        country = by_code.get((work.country_code or "").upper())
        if country is not None:
            work.countries.add(country)


class Migration(migrations.Migration):
    dependencies = [
        ("works", "0030_country_slug"),
    ]

    operations = [
        migrations.AddField(
            model_name="work",
            name="countries",
            field=models.ManyToManyField(
                blank=True,
                help_text="Countries whose outline intersects the work's geometry "
                "(offline point-in-polygon join; multi-valued for transboundary studies).",
                related_name="works",
                to="works.country",
            ),
        ),
        migrations.RunPython(link_existing_country_codes, migrations.RunPython.noop),
        # Drop the dependent view first so DROP COLUMN doesn't silently cascade it away.
        migrations.RunSQL(_DROP_VIEW, reverse_sql=_CREATE_VIEW_LEGACY),
        migrations.RemoveField(
            model_name="work",
            name="country_code",
        ),
        # Recreate the view exposing aggregated country_codes from the M2M.
        migrations.RunSQL(_CREATE_VIEW, reverse_sql=_DROP_VIEW),
    ]
