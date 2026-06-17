# SPDX-FileCopyrightText: 2025 OPTIMETA and KOMET projects <https://projects.tib.eu/komet>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Bridge Django's database configuration into pygeoapi's PostgreSQL providers.

``DATABASE_URL`` is the single source of truth for the database connection.
``etc/pygeoapi-config.yml`` carries no real credentials; this module injects the
host/port/dbname/user/password from Django's parsed ``DATABASES['default']`` into
every PostgreSQL provider in the pygeoapi config, so the OGC API (/ogcapi/)
always connects to the same database as Django.

Kept free of Django imports so ``optimap/settings.py`` can import it while
settings are still loading.
"""

# (pygeoapi key, Django DATABASES key)
_DB_KEY_MAP = (
    ("host", "HOST"),
    ("port", "PORT"),
    ("dbname", "NAME"),
    ("user", "USER"),
    ("password", "PASSWORD"),
)


def apply_db_connection(config: dict, db: dict) -> dict:
    """Inject ``db`` (a Django ``DATABASES['default']`` dict) into ``config``.

    Mutates and returns ``config``. Fields that Django does not supply (e.g. an
    empty ``HOST`` for socket/peer authentication) are left untouched so the
    YAML literal fallback applies.
    """
    for resource in config.get("resources", {}).values():
        for provider in resource.get("providers", []):
            if provider.get("name") == "PostgreSQL":
                data = provider.setdefault("data", {})
                for pg_key, dj_key in _DB_KEY_MAP:
                    value = db.get(dj_key)
                    if value not in (None, ""):
                        data[pg_key] = value
    return config
