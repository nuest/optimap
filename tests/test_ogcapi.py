# SPDX-FileCopyrightText: 2025 OPTIMETA and KOMET projects <https://projects.tib.eu/komet>
# SPDX-License-Identifier: GPL-3.0-or-later

"""End-to-end tests for the OGC API - Features endpoint (/ogcapi/, pygeoapi).

These exercise the live endpoint so they catch the class of misconfiguration
where pygeoapi's PostgreSQL provider cannot reach the database. Historically the
config substituted a separate set of ``OPTIMAP_DB_*`` environment variables that
no deployment set, so pygeoapi fell back to stale default credentials and the
works collection could not connect. The DB connection is now derived from
Django's ``DATABASE_URL`` via ``optimap.pygeoapi_db.apply_db_connection``; a
request that returns features proves the provider connected.
"""

from datetime import date
from unittest import skipUnless

from django.conf import settings
from django.contrib.gis.geos import GeometryCollection, Point
from django.db import connection
from django.test import Client, TransactionTestCase

from works.models import Work

PYGEOAPI_ENABLED = getattr(settings, "PYGEOAPI_ENABLED", False)


@skipUnless(PYGEOAPI_ENABLED, "pygeoapi/OGC API not enabled (config or openapi document missing)")
class OgcApiEndpointTest(TransactionTestCase):
    """Hit /ogcapi/ against the test database with a real published work.

    Uses TransactionTestCase so the work is committed and therefore visible to
    pygeoapi's own (separate) database connection. settings.PYGEOAPI_CONFIG
    captured the non-test database *name* at import time, so setUp redirects the
    provider to the test database — but only the name; the host/user/password
    are left as settings.py produced them, so the endpoint genuinely connects
    with the credentials the application configured.
    """

    def setUp(self):
        self.client = Client()
        self._providers = [
            p
            for resource in settings.PYGEOAPI_CONFIG["resources"].values()
            for p in resource.get("providers", [])
            if p.get("name") == "PostgreSQL"
        ]
        self._saved = [dict(p["data"]) for p in self._providers]
        test_db_name = connection.settings_dict["NAME"]
        for provider in self._providers:
            provider["data"]["dbname"] = test_db_name

        self.work = Work.objects.create(
            title="OGC API Reachability Probe",
            abstract="Ensures pygeoapi connects to the database.",
            url="https://example.com/ogc-probe",
            status="p",
            publicationDate=date(2026, 1, 1),
            geometry=GeometryCollection(Point(7.0, 51.0)),
        )

    def tearDown(self):
        Work.objects.all().delete()
        for provider, saved in zip(self._providers, self._saved):
            provider["data"] = saved
        self._release_pygeoapi_connections()

    @staticmethod
    def _release_pygeoapi_connections():
        # pygeoapi opens its own pooled SQLAlchemy connection(s) to the test
        # database (its engine is process-global via functools.cache). Drop the
        # cached engine and terminate the lingering server-side session(s) —
        # scoped to the current test database — so the test runner can DROP it.
        try:
            from pygeoapi.provider.sql import get_engine

            get_engine.cache_clear()
        except Exception:
            pass
        with connection.cursor() as cur:
            cur.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = current_database() AND pid <> pg_backend_pid()"
            )

    def test_landing_page_is_available(self):
        resp = self.client.get("/ogcapi/?f=json", follow=True)
        self.assertEqual(resp.status_code, 200, resp.content[:500])
        self.assertIn("links", resp.json())

    def test_collections_metadata_lists_works(self):
        resp = self.client.get("/ogcapi/collections?f=json", follow=True)
        self.assertEqual(resp.status_code, 200, resp.content[:500])
        ids = [c.get("id") for c in resp.json().get("collections", [])]
        self.assertIn("works", ids)

    def test_items_endpoint_returns_published_work(self):
        # A 200 with our feature proves the provider actually connected to and
        # queried the database — the regression this guards against.
        resp = self.client.get("/ogcapi/collections/works/items?f=json&limit=50", follow=True)
        self.assertEqual(resp.status_code, 200, resp.content[:500])
        body = resp.json()
        self.assertEqual(body["type"], "FeatureCollection")
        titles = [f["properties"].get("title") for f in body["features"]]
        self.assertIn("OGC API Reachability Probe", titles)

    def test_single_item_endpoint_returns_feature(self):
        resp = self.client.get(f"/ogcapi/collections/works/items/{self.work.id}?f=json", follow=True)
        self.assertEqual(resp.status_code, 200, resp.content[:500])
        body = resp.json()
        self.assertEqual(body["type"], "Feature")
        self.assertEqual(body["properties"].get("title"), "OGC API Reachability Probe")

    def test_items_endpoint_excludes_unpublished_works(self):
        # The provider reads the works_published view (status = 'p' only).
        Work.objects.create(
            title="OGC API Draft (should be hidden)",
            url="https://example.com/ogc-draft",
            status="h",
            publicationDate=date(2026, 1, 2),
            geometry=GeometryCollection(Point(8.0, 52.0)),
        )
        resp = self.client.get("/ogcapi/collections/works/items?f=json&limit=50", follow=True)
        self.assertEqual(resp.status_code, 200, resp.content[:500])
        titles = [f["properties"].get("title") for f in resp.json()["features"]]
        self.assertIn("OGC API Reachability Probe", titles)
        self.assertNotIn("OGC API Draft (should be hidden)", titles)
