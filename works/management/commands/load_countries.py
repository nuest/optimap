# SPDX-FileCopyrightText: 2026 OPTIMETA and KOMET projects <https://projects.tib.eu/komet>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Load country outlines into the :class:`works.models.Country` table.

Mirrors ``load_global_regions``: retrieve → simplify → store. The source is the
Natural Earth 110m Admin-0 Countries dataset (public domain). The downloaded
GeoJSON is cached next to this command (or in ``GLOBAL_REGIONS_DATA_DIR`` when
set) so re-runs and deployments don't re-download. Geometries are simplified
with ``COUNTRY_SIMPLIFICATION_TOLERANCE`` before storing — they drive the
``/at/<country>`` pages and a toggleable countries map layer, neither of which
needs full-resolution borders.

Usage:
    python manage.py load_countries
    python manage.py load_countries --force        # re-download + reload
    python manage.py load_countries --tolerance 0  # store unsimplified
"""

import os
import shutil
import urllib.request

from django.conf import settings
from django.contrib.gis.gdal import DataSource
from django.contrib.gis.geos import MultiPolygon, Polygon
from django.core.management.base import BaseCommand
from django.utils.text import slugify

from works.models import Country

COMMAND_DIR = os.path.dirname(__file__)

# Natural Earth 1:50m Admin-0 Countries (public domain). The 50m resolution is
# used (not 110m) so borders align well on the map; light simplification keeps
# the payload modest. Field names: NAME_EN (English name), ISO_A2 (ISO 3166-1
# alpha-2; "-99" where Natural Earth has no code, falling back to ISO_A2_EH),
# CONTINENT. The official naciscdn host 403s without a User-Agent; the
# nvkelso/natural-earth-vector GitHub mirror is the documented stable alternative.
COUNTRIES_URL = (
    "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_50m_admin_0_countries.geojson"
)
COUNTRIES_FILE = "ne_50m_admin_0_countries.geojson"
COUNTRIES_LICENSE = "https://www.naturalearthdata.com/about/terms-of-use/"  # public domain


def _data_dir():
    # Read at call time so override_settings(GLOBAL_REGIONS_DATA_DIR=...) is honored.
    return settings.GLOBAL_REGIONS_DATA_DIR or COMMAND_DIR


def _first_field(feat, *names):
    """Return the first present, non-empty field value among ``names``."""
    available = set(feat.fields)
    for name in names:
        if name in available:
            value = feat.get(name)
            if value not in (None, "", "-99"):
                return value
    return None


def _iso_a2(feat):
    """First clean ISO 3166-1 alpha-2 code (two ASCII letters), else None.

    Natural Earth occasionally stores a non-standard value in ISO_A2 (e.g.
    Taiwan = "CN-TW"); ISO_A2_EH usually carries the plain alpha-2 there.
    """
    available = set(feat.fields)
    for name in ("ISO_A2", "ISO_A2_EH", "iso_a2"):
        if name in available:
            value = feat.get(name)
            if value and len(value) == 2 and value.isascii() and value.isalpha():
                return value.upper()
    return None


class Command(BaseCommand):
    help = "Load simplified country outlines (Natural Earth 110m) into the Country model."

    def add_arguments(self, parser):
        parser.add_argument(
            "--force",
            action="store_true",
            help="Re-download the source file and reload all countries.",
        )
        parser.add_argument(
            "--tolerance",
            type=float,
            default=None,
            help="Override COUNTRY_SIMPLIFICATION_TOLERANCE (0 disables simplification).",
        )

    def handle(self, *args, **options):
        data_dir = _data_dir()
        if settings.GLOBAL_REGIONS_DATA_DIR and not os.path.exists(data_dir):
            os.makedirs(data_dir, exist_ok=True)

        countries_path = os.path.join(data_dir, COUNTRIES_FILE)
        if options["force"] and os.path.exists(countries_path):
            os.remove(countries_path)

        if os.path.exists(countries_path):
            self.stdout.write(f"Using cached {countries_path} (delete or pass --force to re-download)")
        else:
            self.stdout.write("Downloading Natural Earth 110m Admin-0 Countries…")
            req = urllib.request.Request(COUNTRIES_URL, headers={"User-Agent": "OPTIMAP/load_countries"})
            with urllib.request.urlopen(req) as resp, open(countries_path, "wb") as out:
                shutil.copyfileobj(resp, out)

        tolerance = options["tolerance"]
        if tolerance is None:
            tolerance = getattr(settings, "COUNTRY_SIMPLIFICATION_TOLERANCE", 0.05)

        # DataSource does not support automatic closing; delete the object manually
        # below, see https://docs.djangoproject.com/en/5.2/ref/contrib/gis/gdal/#datasource
        ds = DataSource(countries_path)
        layer = ds[0]

        # Several Natural Earth features can share one ISO_A2 (e.g. Australia plus
        # its tiny "Australian Indian Ocean Territories" / "Ashmore and Cartier
        # Islands" dependencies all carry AU). iso_code is unique on Country, so
        # MERGE all features for a code into one geometry; the display name and
        # continent come from the largest-area feature (the sovereign country).
        groups = {}  # iso_code -> {"best": (area, name, continent), "geoms": [geos_geom, ...]}
        skipped_n = 0
        for feat in layer:
            iso_code = _iso_a2(feat)
            name = _first_field(feat, "NAME_EN", "ADMIN", "NAME", "name")
            if not iso_code or not name:
                skipped_n += 1
                continue
            geom = feat.geom.geos
            entry = groups.setdefault(iso_code, {"best": None, "geoms": []})
            entry["geoms"].append(geom)
            area = geom.area
            if entry["best"] is None or area > entry["best"][0]:
                continent = _first_field(feat, "CONTINENT", "continent") or ""
                entry["best"] = (area, name, continent)
        del ds  # We cannot close the source but can only rely on the GC

        created_n = updated_n = merged_n = 0
        for iso_code, entry in groups.items():
            _area, name, continent = entry["best"]
            geoms = entry["geoms"]
            geom = geoms[0]
            if len(geoms) > 1:
                for extra in geoms[1:]:
                    geom = geom.union(extra)
                merged_n += 1
            if tolerance and tolerance > 0:
                geom = geom.simplify(tolerance, preserve_topology=True)
            if isinstance(geom, Polygon):
                geom = MultiPolygon([geom])
            _, created = Country.objects.update_or_create(
                iso_code=iso_code,
                defaults={"name": name, "slug": slugify(name), "continent": continent, "geom": geom},
            )
            created_n += created
            updated_n += not created

        self.stdout.write(
            self.style.SUCCESS(
                f"Countries loaded: {created_n} created, {updated_n} updated, "
                f"{merged_n} merged from multiple features, {skipped_n} skipped (no ISO/name)."
            )
        )
