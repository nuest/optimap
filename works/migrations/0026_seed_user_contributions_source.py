# SPDX-FileCopyrightText: 2026 OPTIMETA and KOMET projects <https://projects.tib.eu/komet>
# SPDX-License-Identifier: GPL-3.0-or-later
"""Seed the dedicated "User contributions" Source for DOI submissions.

Works submitted via the /contribute/ "add a work by DOI" form are attached to
this Source so their provenance is clean and they group together in the admin.
The runtime helper ``works.harvesting.crossref.get_user_contributions_source``
also fetches-or-creates it, so this migration is just a convenience seed.
"""

from django.conf import settings
from django.db import migrations

SOURCE_NAME = "User contributions"


def seed_source(apps, schema_editor):
    Source = apps.get_model("works", "Source")
    # url_field is display-only for a crossref-prefix source (harvesting reads
    # doi_prefix/crossref_filter), so point it at this deployment's own
    # /contribute/ page rather than a hardcoded domain. Admin-editable later.
    Source.objects.get_or_create(
        name=SOURCE_NAME,
        defaults={
            "url_field": f"{settings.BASE_URL.rstrip('/')}/contribute/",
            "source_type": "crossref-prefix",
            "harvest_interval_minutes": 0,
        },
    )


def unseed_source(apps, schema_editor):
    Source = apps.get_model("works", "Source")
    # Only remove the seed row when no works depend on it.
    Source.objects.filter(name=SOURCE_NAME, harvesting_events__isnull=True).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("works", "0025_statisticssnapshot_contributed_dois_and_more"),
    ]

    operations = [
        migrations.RunPython(seed_source, unseed_source),
    ]
