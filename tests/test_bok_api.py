# SPDX-FileCopyrightText: 2026 OPTIMETA and KOMET projects <https://projects.tib.eu/komet>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests for the public /api/v1/bok/search/ endpoint."""

import json
import os
from unittest.mock import patch

from django.core.cache import cache
from django.test import Client, TestCase

from works.bok import client as bok_client

FIXTURE_PATH = os.path.join(os.path.dirname(__file__), "fixtures", "bok_sample.json")


def _seed_cache():
    cache.clear()
    with open(FIXTURE_PATH) as fh:
        raw = json.load(fh)
    with patch.object(bok_client, "_bok_session") as session_factory:
        session_factory.return_value.get.return_value.json.return_value = raw
        snapshot = bok_client.fetch_bok_snapshot()
    cache.set(bok_client._cache_key(), snapshot)


class BokSearchEndpointTests(TestCase):
    def setUp(self):
        _seed_cache()
        self.client = Client()

    def test_short_query_returns_empty(self):
        resp = self.client.get("/api/v1/bok/search/?q=ca")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["count"], 0)
        self.assertEqual(body["results"], [])
        self.assertEqual(body["min_query_length"], 3)

    def test_match_returns_breadcrumb_and_uri(self):
        resp = self.client.get("/api/v1/bok/search/?q=cartography")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertGreaterEqual(body["count"], 1)
        cv = next(r for r in body["results"] if r["code"] == "CV")
        self.assertEqual(cv["uri"], "https://geospacebok.eu/CV")
        self.assertEqual(cv["parent_code"], "GIST")
        self.assertEqual(cv["breadcrumb"][0]["code"], "GIST")

    def test_limit_param_caps_results(self):
        resp = self.client.get("/api/v1/bok/search/?q=spat&limit=1")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertLessEqual(body["count"], 1)
