# SPDX-FileCopyrightText: 2025 OPTIMETA and KOMET projects <https://projects.tib.eu/komet>
# SPDX-License-Identifier: GPL-3.0-or-later

from django.conf import settings
from django.core.cache import cache

import optimap


def get_version(request):
    """
    Return package version as listed in `__version__` in `init.py`.
    """
    return {"optimap_version": optimap.__version__}


def gazetteer_settings(request):
    """
    Return gazetteer/geocoding settings for use in templates.
    """
    return {
        "gazetteer_provider": getattr(settings, "GAZETTEER_PROVIDER", "nominatim"),
        "gazetteer_placeholder": getattr(settings, "GAZETTEER_PLACEHOLDER", "Search for a location..."),
        "gazetteer_api_key": getattr(settings, "GAZETTEER_API_KEY", ""),
    }


def basemap_settings(request):
    """Return enabled base-map layer definitions for the Leaflet layer switcher.

    Serialized as a list of {provider_key, label, default, options} dicts and
    injected into every page via ``{{ optimap_basemaps|json_script:"optimap-basemaps" }}``
    in base.html.  The result is cached for 5 minutes to avoid a DB hit on every
    request (base layers change very rarely).
    """

    def _load():
        try:
            from works.models import BaseMapLayer

            return BaseMapLayer.enabled_layers()
        except Exception:  # noqa: BLE001 — table may not exist yet (first migrate)
            return []

    layers = cache.get_or_set("optimap_basemaps", _load, 300)
    has_maplibre = any(layer.get("provider_key") == "BasemapWorldVector" for layer in layers)
    return {"optimap_basemaps": layers, "has_maplibre_basemap": has_maplibre}
