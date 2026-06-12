# SPDX-FileCopyrightText: 2026 OPTIMETA and KOMET projects <https://projects.tib.eu/komet>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests for the BoK concept contribution endpoint."""

import json
import os
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import Client, TestCase, override_settings
from django.utils import timezone

from works.bok import client as bok_client
from works.models import Collection, Contribution, Source, Work

User = get_user_model()
FIXTURE_PATH = os.path.join(os.path.dirname(__file__), "fixtures", "bok_sample.json")


def _seed_cache():
    cache.clear()
    with open(FIXTURE_PATH) as fh:
        raw = json.load(fh)
    with patch.object(bok_client, "_bok_session") as session_factory:
        session_factory.return_value.get.return_value.json.return_value = raw
        snapshot = bok_client.fetch_bok_snapshot()
    cache.set(bok_client._cache_key(), snapshot)


@override_settings(BOK_ENABLED_COLLECTIONS=["test-collection"])
class ContributeBokTests(TestCase):
    def setUp(self):
        _seed_cache()
        self.client = Client()
        self.user = User.objects.create_user(
            username="bobok@example.com",
            email="bobok@example.com",
            password="testpass123",
        )
        self.source = Source.objects.create(
            name="Test Journal",
            url_field="https://example.com/oai",
        )
        # The BoK editor is opt-in via OPTIMAP_BOK_ENABLED_COLLECTIONS; the
        # class-level override above turns it on for "test-collection", and
        # we put the test work in that collection.
        self.collection = Collection.objects.create(
            identifier="test-collection",
            name="Test Collection",
            is_published=True,
        )
        self.work = Work.objects.create(
            title="Test work",
            source=self.source,
            status="h",
            creationDate=timezone.now(),
        )
        self.work.collections.add(self.collection)

    def _post(self, body, login=True):
        if login:
            self.client.login(username="bobok@example.com", password="testpass123")
        return self.client.post(
            f"/work/{self.work.id}/contribute-bok/",
            data=json.dumps(body),
            content_type="application/json",
        )

    def test_anonymous_blocked(self):
        resp = self._post({"add": ["CV"]}, login=False)
        self.assertEqual(resp.status_code, 401)

    def test_unknown_code_rejected(self):
        resp = self._post({"add": ["NOPE", "CV"]})
        self.assertEqual(resp.status_code, 400)
        self.assertIn("Unknown", resp.json()["error"])
        self.work.refresh_from_db()
        self.assertIsNone(self.work.bok_concepts)

    def test_empty_add_and_remove_rejected(self):
        resp = self._post({"add": [], "remove": []})
        self.assertEqual(resp.status_code, 400)

    def test_first_add_flips_status_h_to_c(self):
        # Pre-state: harvested.
        self.assertEqual(self.work.status, "h")
        resp = self._post({"add": ["CV", "AM10"]})
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(sorted(body["bok_concepts"]), ["AM10", "CV"])
        self.assertEqual(body["status"], "c")
        self.work.refresh_from_db()
        self.assertEqual(self.work.status, "c")
        self.assertEqual(sorted(self.work.bok_concepts), ["AM10", "CV"])

    def test_recognition_board_one_row_per_user_regardless_of_concept_count(self):
        # Adding multiple concepts in one POST = 1 ontology row for this user.
        self._post({"add": ["CV", "AM10"]})
        rows = Contribution.objects.filter(work=self.work, kind=Contribution.ONTOLOGY)
        self.assertEqual(rows.count(), 1)

    def test_recognition_board_dedupes_repeat_contributions_by_same_user(self):
        # Two POSTs by the same user => still 1 row.
        self._post({"add": ["CV"]})
        self._post({"add": ["AM10"]})
        rows = Contribution.objects.filter(
            user=self.user,
            work=self.work,
            kind=Contribution.ONTOLOGY,
        )
        self.assertEqual(rows.count(), 1)

    def test_recognition_board_counts_each_user_separately(self):
        # Two different users => 2 rows.
        self._post({"add": ["CV"]})
        other = User.objects.create_user(
            username="zsuser@example.com",
            email="zsuser@example.com",
            password="x",
        )
        self.client.login(username="zsuser@example.com", password="x")
        self.client.post(
            f"/work/{self.work.id}/contribute-bok/",
            data=json.dumps({"add": ["AM10"]}),
            content_type="application/json",
        )
        rows = Contribution.objects.filter(work=self.work, kind=Contribution.ONTOLOGY)
        self.assertEqual(rows.count(), 2)
        self.assertEqual(
            sorted(r.user_id for r in rows),
            sorted([self.user.id, other.id]),
        )

    def test_remove_does_not_create_recognition_row(self):
        self.work.bok_concepts = ["CV", "AM10"]
        self.work.save()
        self._post({"remove": ["AM10"]})
        rows = Contribution.objects.filter(work=self.work, kind=Contribution.ONTOLOGY)
        self.assertEqual(rows.count(), 0)
        self.work.refresh_from_db()
        self.assertEqual(self.work.bok_concepts, ["CV"])
        # And status is unchanged because pure removal doesn't promote.
        self.assertEqual(self.work.status, "h")

    def test_provenance_event_records_diff_and_vocabulary(self):
        self._post({"add": ["CV"]})
        self.work.refresh_from_db()
        events = (self.work.provenance or {}).get("events", [])
        bok_events = [e for e in events if e.get("kinds") == ["bok"]]
        self.assertEqual(len(bok_events), 1)
        evt = bok_events[0]
        self.assertEqual(evt["vocabulary"], "eo4geo_bok")
        self.assertEqual(evt["added"], ["CV"])
        self.assertEqual(evt["removed"], [])
        self.assertEqual(evt["status_from"], "h")
        self.assertEqual(evt["status_to"], "c")

    def test_pure_remove_does_not_flip_status(self):
        self.work.bok_concepts = ["CV"]
        self.work.save()
        resp = self._post({"remove": ["CV"]})
        self.assertEqual(resp.status_code, 200)
        self.work.refresh_from_db()
        self.assertEqual(self.work.status, "h")  # unchanged
        self.assertEqual(self.work.bok_concepts, [])

    def test_no_op_returns_200_no_changes(self):
        self.work.bok_concepts = ["CV"]
        self.work.save()
        resp = self._post({"add": ["CV"]})  # already there
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertIn("No changes", body.get("message", ""))

    @override_settings(BOK_ENABLED_COLLECTIONS=["alpha"])
    def test_collection_gate_blocks_work_outside_enabled_collections(self):
        # Work is in "test-collection" but the gate only allows "alpha".
        resp = self._post({"add": ["CV"]})
        self.assertEqual(resp.status_code, 403)
        self.assertIn("alpha", resp.json()["error"])
        self.work.refresh_from_db()
        self.assertIsNone(self.work.bok_concepts)

    @override_settings(BOK_ENABLED_COLLECTIONS=["alpha"])
    def test_collection_gate_allows_work_in_enabled_collection(self):
        alpha = Collection.objects.create(
            identifier="alpha",
            name="Alpha",
            is_published=True,
        )
        self.work.collections.add(alpha)
        resp = self._post({"add": ["CV"]})
        self.assertEqual(resp.status_code, 200)
        self.work.refresh_from_db()
        self.assertEqual(self.work.bok_concepts, ["CV"])

    @override_settings(BOK_ENABLED_COLLECTIONS=[])
    def test_empty_allow_list_blocks_everyone(self):
        # Empty allow-list = editor disabled site-wide.
        resp = self._post({"add": ["CV"]})
        self.assertEqual(resp.status_code, 403)
        self.assertIn("not enabled", resp.json()["error"])
