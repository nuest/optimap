# SPDX-FileCopyrightText: 2022 OPTIMETA and KOMET projects <https://projects.tib.eu/komet>
# SPDX-License-Identifier: GPL-3.0-or-later

from django.contrib.gis.geos import MultiPolygon
from django.db import migrations
from django.utils.text import slugify

SENTINEL_ISO = "ZZ"
SENTINEL_NAME = "No country / not applicable"

# Recreate the works_published view so the aggregated country_codes column (read
# by the pygeoapi /ogcapi/ provider) excludes the sentinel — otherwise a
# curator-excluded work would leak "ZZ" through the OGC API. Mirrors the view in
# migration 0031, plus the `c.iso_code <> 'ZZ'` filter.
_CREATE_VIEW = """
CREATE OR REPLACE VIEW works_published AS
    SELECT w.*,
           (SELECT string_agg(c.iso_code, ',' ORDER BY c.iso_code)
              FROM works_work_countries wc
              JOIN works_country c ON c.id = wc.country_id
             WHERE wc.work_id = w.id AND c.iso_code <> 'ZZ') AS country_codes
      FROM works_work w
     WHERE w.status = 'p';
"""

# Reverse: the pre-sentinel view from migration 0031 (no ZZ filter).
_CREATE_VIEW_031 = """
CREATE OR REPLACE VIEW works_published AS
    SELECT w.*,
           (SELECT string_agg(c.iso_code, ',' ORDER BY c.iso_code)
              FROM works_work_countries wc
              JOIN works_country c ON c.id = wc.country_id
             WHERE wc.work_id = w.id) AS country_codes
      FROM works_work w
     WHERE w.status = 'p';
"""


def create_sentinel(apps, schema_editor):
    Country = apps.get_model("works", "Country")
    Country.objects.update_or_create(
        iso_code=SENTINEL_ISO,
        defaults={
            "name": SENTINEL_NAME,
            "slug": slugify(SENTINEL_NAME),
            "continent": "",
            # Empty geometry: the point-in-polygon join never intersects it, so
            # the sentinel is only ever assigned by manual curation.
            "geom": MultiPolygon(srid=4326),
        },
    )


def remove_sentinel(apps, schema_editor):
    Country = apps.get_model("works", "Country")
    Country.objects.filter(iso_code=SENTINEL_ISO).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("works", "0031_work_countries"),
    ]

    operations = [
        migrations.RunPython(create_sentinel, remove_sentinel),
        migrations.RunSQL(_CREATE_VIEW, reverse_sql=_CREATE_VIEW_031),
    ]
