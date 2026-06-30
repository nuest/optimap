# Generated migration — add basemap.world Web Vector (BKG) as a disabled-by-default BaseMapLayer
# SPDX-FileCopyrightText: 2026 OPTIMETA and KOMET projects <https://projects.tib.eu/komet>
# SPDX-License-Identifier: GPL-3.0-or-later

from django.db import migrations

NEW_LAYER = {
    "provider_key": "BasemapWorldVector",
    "label": "basemap.world (vector, BKG)",
    "enabled": False,
    "is_default": False,
    "order": 20,
    "options": {
        "style": "https://sgx.geodatenzentrum.de/gdz_basemapworld_vektor/styles/bm_web_wld_col.json"
    },
}


def seed(apps, schema_editor):
    BaseMapLayer = apps.get_model("works", "BaseMapLayer")
    BaseMapLayer.objects.get_or_create(
        provider_key=NEW_LAYER["provider_key"], defaults=NEW_LAYER
    )


def unseed(apps, schema_editor):
    BaseMapLayer = apps.get_model("works", "BaseMapLayer")
    BaseMapLayer.objects.filter(provider_key=NEW_LAYER["provider_key"]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("works", "0036_basemaplayer_seed"),
    ]

    operations = [
        migrations.RunPython(seed, reverse_code=unseed),
    ]
