# SPDX-FileCopyrightText: 2026 OPTIMETA and KOMET projects <https://projects.tib.eu/komet>
# SPDX-License-Identifier: GPL-3.0-or-later

import re

from django.db import migrations


_S_ID_RE = re.compile(r"S\d+", re.IGNORECASE)


def backfill_openalex_id(apps, schema_editor):
    """Copy ``openalex_url``'s S<id> into ``openalex_id`` where the latter is empty."""
    Source = apps.get_model("works", "Source")
    for src in Source.objects.exclude(openalex_url__isnull=True).exclude(openalex_url__exact=""):
        if src.openalex_id:
            continue
        match = _S_ID_RE.search(src.openalex_url)
        if match:
            src.openalex_id = match.group(0).upper()
            src.save(update_fields=["openalex_id"])


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("works", "0005_source_field_help_texts"),
    ]

    operations = [
        migrations.RunPython(backfill_openalex_id, noop_reverse),
        migrations.RemoveField(
            model_name="source",
            name="openalex_url",
        ),
    ]
