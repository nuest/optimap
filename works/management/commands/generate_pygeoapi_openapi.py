# SPDX-FileCopyrightText: 2025 OPTIMETA and KOMET projects <https://projects.tib.eu/komet>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Generate the pygeoapi OpenAPI document from etc/pygeoapi-config.yml.

Run once after install and whenever etc/pygeoapi-config.yml changes:

    python manage.py generate_pygeoapi_openapi

The output is written to etc/pygeoapi-openapi.yml (next to the config).
Django's OGC API endpoint (/ogcapi/) will not activate until this file exists.

The PostgreSQL connection is taken from Django's DATABASES / DATABASE_URL (not
from the YAML), so a reachable database is required at generation time for the
``works`` collection to be introspected and included in the OpenAPI document.
"""

import os
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Generate etc/pygeoapi-openapi.yml from etc/pygeoapi-config.yml"

    def add_arguments(self, parser):
        parser.add_argument(
            "--force",
            action="store_true",
            help="Overwrite existing openapi file",
        )

    def handle(self, *args, **options):
        config_path = Path(settings.BASE_DIR) / "etc" / "pygeoapi-config.yml"
        openapi_path = Path(settings.BASE_DIR) / "etc" / "pygeoapi-openapi.yml"

        if not config_path.exists():
            raise CommandError(f"pygeoapi config not found: {config_path}")

        if openapi_path.exists() and not options["force"]:
            self.stdout.write(
                self.style.WARNING(f"OpenAPI file already exists: {openapi_path}\nUse --force to regenerate.")
            )
            return

        os.environ.setdefault("PYGEOAPI_CONFIG", str(config_path))
        os.environ.setdefault("PYGEOAPI_OPENAPI", str(openapi_path))

        try:
            import yaml
            from pygeoapi.config import get_config
            from pygeoapi.openapi import get_oas
        except ImportError as exc:
            raise CommandError(f"pygeoapi not installed: {exc}") from exc

        from optimap.pygeoapi_db import apply_db_connection

        self.stdout.write(f"Generating OpenAPI document from {config_path} ...")
        try:
            # DATABASE_URL is the single source of truth: inject Django's parsed
            # DB connection so pygeoapi can introspect the works collection.
            cfg = apply_db_connection(get_config(), settings.DATABASES["default"])
            oas = get_oas(cfg, fail_on_invalid_collection=False)
            doc = yaml.safe_dump(oas, default_flow_style=False)
        except Exception as exc:
            raise CommandError(f"OpenAPI generation failed: {exc}") from exc

        openapi_path.write_text(doc, encoding="utf-8")
        self.stdout.write(self.style.SUCCESS(f"Written to {openapi_path}"))
        self.stdout.write("Restart the server to activate the /ogcapi/ endpoint.")
