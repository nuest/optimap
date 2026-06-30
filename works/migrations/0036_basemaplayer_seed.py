# Generated migration — seed default BaseMapLayer rows
# SPDX-FileCopyrightText: 2025 OPTIMETA and KOMET projects <https://projects.tib.eu/komet>
# SPDX-License-Identifier: GPL-3.0-or-later

from django.db import migrations

SEED_LAYERS = [
    # Enabled layers (the four keyless defaults)
    {
        "provider_key": "OpenStreetMap.Mapnik",
        "label": "OpenStreetMap",
        "enabled": True,
        "is_default": True,
        "order": 0,
        "options": {},
    },
    {
        "provider_key": "CartoDB.Voyager",
        "label": "CARTO (English labels)",
        "enabled": True,
        "is_default": False,
        "order": 1,
        "options": {},
    },
    {
        "provider_key": "Esri.WorldImagery",
        "label": "Esri World Imagery (satellite)",
        "enabled": True,
        "is_default": False,
        "order": 2,
        "options": {},
    },
    {
        "provider_key": "OpenTopoMap",
        "label": "OpenTopoMap (topographic)",
        "enabled": True,
        "is_default": False,
        "order": 3,
        "options": {},
    },
    # Disabled extras — admins can flip them on; key-required ones need options set too
    {
        "provider_key": "CartoDB.Positron",
        "label": "CARTO Positron (light)",
        "enabled": False,
        "is_default": False,
        "order": 10,
        "options": {},
    },
    {
        "provider_key": "Esri.WorldStreetMap",
        "label": "Esri World Street Map",
        "enabled": False,
        "is_default": False,
        "order": 11,
        "options": {},
    },
    {
        "provider_key": "Stadia.AlidadeSmooth",
        "label": "Stadia Alidade Smooth",
        "enabled": False,
        "is_default": False,
        "order": 12,
        "options": {},
    },
    {
        "provider_key": "Stadia.AlidadeSmoothDark",
        "label": "Stadia Alidade Smooth Dark",
        "enabled": False,
        "is_default": False,
        "order": 13,
        "options": {},
    },
    {
        "provider_key": "Stadia.StamenToner",
        "label": "Stamen Toner (B&W)",
        "enabled": False,
        "is_default": False,
        "order": 14,
        "options": {},
    },
    {
        "provider_key": "Stadia.StamenWatercolor",
        "label": "Stamen Watercolor",
        "enabled": False,
        "is_default": False,
        "order": 15,
        "options": {},
    },
]


def seed_basemap_layers(apps, schema_editor):
    BaseMapLayer = apps.get_model("works", "BaseMapLayer")
    for data in SEED_LAYERS:
        BaseMapLayer.objects.get_or_create(provider_key=data["provider_key"], defaults=data)


def unseed_basemap_layers(apps, schema_editor):
    BaseMapLayer = apps.get_model("works", "BaseMapLayer")
    keys = [d["provider_key"] for d in SEED_LAYERS]
    BaseMapLayer.objects.filter(provider_key__in=keys).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("works", "0035_basemaplayer"),
    ]

    operations = [
        migrations.RunPython(seed_basemap_layers, reverse_code=unseed_basemap_layers),
    ]
