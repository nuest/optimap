# SPDX-FileCopyrightText: 2026 OPTIMETA and KOMET projects <https://projects.tib.eu/komet>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Unit tests for the EO4GEO BoK client / cache wrapper."""

import json
import os
from unittest.mock import patch

from django.core.cache import cache
from django.test import TestCase, override_settings, tag

from works.bok import client as bok_client


FIXTURE_PATH = os.path.join(os.path.dirname(__file__), "fixtures", "bok_sample.json")


def _load_fixture() -> dict:
    with open(FIXTURE_PATH) as fh:
        return json.load(fh)


class BokTrimAndDeriveTests(TestCase):
    def setUp(self):
        cache.clear()

    def test_fetch_trims_to_required_fields(self):
        with patch.object(bok_client, "_bok_session") as session_factory:
            session = session_factory.return_value
            session.get.return_value.json.return_value = _load_fixture()
            session.get.return_value.raise_for_status.return_value = None

            snapshot = bok_client.fetch_bok_snapshot()

        self.assertEqual(set(snapshot.keys()), {"GIST", "CV", "AM", "AM10", "AM10-3"})
        cv = snapshot["CV"]
        self.assertEqual(cv["code"], "CV")
        self.assertEqual(cv["name"], "Cartography and Visualization")
        self.assertEqual(cv["uri"], "https://geospacebok.eu/CV")
        # parent of CV is GIST.
        self.assertEqual(cv["parent_code"], "GIST")
        self.assertEqual(cv["breadcrumb"], [{"code": "GIST", "name": "Geographic Information Science and Technology"}])
        # raw upstream fields we don't need are stripped.
        self.assertNotIn("contributors", cv)
        self.assertNotIn("references", cv)
        self.assertNotIn("skills", cv)

    def test_breadcrumb_chains_through_multiple_parents(self):
        with patch.object(bok_client, "_bok_session") as session_factory:
            session_factory.return_value.get.return_value.json.return_value = _load_fixture()
            snapshot = bok_client.fetch_bok_snapshot()

        leaf = snapshot["AM10-3"]
        self.assertEqual(leaf["parent_code"], "AM10")
        self.assertEqual(
            [b["code"] for b in leaf["breadcrumb"]],
            ["GIST", "AM", "AM10"],
        )

    def test_get_concepts_caches_after_first_call(self):
        with patch.object(bok_client, "fetch_bok_snapshot") as fake_fetch:
            fake_fetch.return_value = {"CV": {"code": "CV", "name": "Cartography", "uri": "", "description": "", "parent_code": "", "breadcrumb": []}}
            cache.clear()
            bok_client.get_concepts()
            bok_client.get_concepts()
            self.assertEqual(fake_fetch.call_count, 1)

    def test_resolve_marks_unknown_codes_as_orphan(self):
        with patch.object(bok_client, "fetch_bok_snapshot") as fake_fetch:
            fake_fetch.return_value = {"CV": {"code": "CV", "name": "Cartography", "uri": "https://geospacebok.eu/CV", "description": "x", "parent_code": "", "breadcrumb": []}}
            cache.clear()
            resolved = bok_client.resolve(["CV", "REMOVED"])
        self.assertEqual(resolved[0]["code"], "CV")
        self.assertFalse(resolved[0]["orphan"])
        self.assertEqual(resolved[1]["code"], "REMOVED")
        self.assertTrue(resolved[1]["orphan"])
        self.assertEqual(resolved[1]["uri"], "")


class BokSearchRankingTests(TestCase):
    def setUp(self):
        cache.clear()
        # Build the trimmed snapshot once and seed the cache so search/get
        # don't try to refetch over the network.
        with patch.object(bok_client, "_bok_session") as session_factory:
            session_factory.return_value.get.return_value.json.return_value = _load_fixture()
            session_factory.return_value.get.return_value.raise_for_status.return_value = None
            snapshot = bok_client.fetch_bok_snapshot()
        cache.set(bok_client._cache_key(), snapshot)

    def test_short_query_returns_empty(self):
        self.assertEqual(bok_client.search(""), [])
        self.assertEqual(bok_client.search("ca"), [])

    def test_exact_code_ranks_first(self):
        results = bok_client.search("am10")
        self.assertGreaterEqual(len(results), 1)
        self.assertEqual(results[0]["code"], "AM10")

    def test_name_substring_match_returns_concept(self):
        results = bok_client.search("cartography")
        codes = [r["code"] for r in results]
        self.assertIn("CV", codes)

    def test_limit_caps_results(self):
        results = bok_client.search("a", limit=2)
        # 'a' is too short — should still empty out:
        self.assertEqual(results, [])
        results = bok_client.search("spat", limit=1)
        self.assertLessEqual(len(results), 1)


class BokOnlineSmokeTests(TestCase):
    """Smoke test against the real Firebase endpoint to catch upstream
    schema drift. Skipped by default — opt in with `--tag=online`."""

    @tag("online")
    def test_real_fetch_has_known_concepts(self):
        cache.clear()
        snapshot = bok_client.fetch_bok_snapshot()
        # CV / GIST have been in the BoK since v1; AM10 is a known leaf.
        self.assertIn("CV", snapshot)
        self.assertIn("GIST", snapshot)
        self.assertGreater(len(snapshot), 100)
