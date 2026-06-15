# SPDX-FileCopyrightText: 2026 OPTIMETA and KOMET projects <https://projects.tib.eu/komet>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Rename the AGILE-GISS collection to AGILE GIS.

Renames identifier agile-giss → agile-gis and display name "AGILE-GISS" →
"AGILE GIS" to reflect that the collection now contains papers from both the
Copernicus AGILE: GIScience Series (2020–present) and the Springer Lecture
Notes in Geoinformation and Cartography series (2008–2019).

The description is also updated to explain both sources.

Safe: only touches rows where identifier='agile-giss'. A short_slug (if set)
is preserved so any vanity URL keeps working.
"""

from django.db import migrations

DESCRIPTION = (
    "Full papers from the AGILE International Conference on Geographic Information Science, "
    "the annual meeting of the Association of Geographic Information Laboratories in Europe "
    "(AGILE, established 1998). "
    "Peer-reviewed full papers published by Springer in the Lecture Notes in Geoinformation "
    "and Cartography series (2004–2019) and in open access by Copernicus Publications "
    "in the AGILE: GIScience Series (2020–present). "
    "Short papers and poster abstracts are not included."
)


def rename_agile_collection(apps, schema_editor):
    Collection = apps.get_model("works", "Collection")
    Collection.objects.filter(identifier="agile-giss").update(
        identifier="agile-gis",
        name="AGILE GIS",
        description=DESCRIPTION,
    )


def reverse_rename_agile_collection(apps, schema_editor):
    Collection = apps.get_model("works", "Collection")
    Collection.objects.filter(identifier="agile-gis").update(
        identifier="agile-giss",
        name="AGILE-GISS",
        description="",
    )


class Migration(migrations.Migration):
    dependencies = [
        ("works", "0018_collection_logo_url"),
    ]

    operations = [
        migrations.RunPython(
            rename_agile_collection,
            reverse_code=reverse_rename_agile_collection,
        ),
    ]
