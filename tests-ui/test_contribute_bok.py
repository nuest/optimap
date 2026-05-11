# SPDX-FileCopyrightText: 2026 OPTIMETA and KOMET projects <https://projects.tib.eu/komet>
# SPDX-License-Identifier: GPL-3.0-or-later

"""UI smoke tests for BoK concept tagging on the work landing page (issue #245).

These run via the Django test client (no Selenium) — they assert that
the right markup is rendered for the right user/work combination. Full
keyboard-interaction tests against a real browser belong in a follow-up
Helium-based test once the foundation has stabilised.
"""

import json
import os
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import Client, TestCase, override_settings
from django.utils import timezone

from works.bok import client as bok_client
from works.models import Collection, Source, Work


User = get_user_model()
FIXTURE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)),
    "tests", "fixtures", "bok_sample.json",
)


def _seed_cache():
    cache.clear()
    with open(FIXTURE_PATH) as fh:
        raw = json.load(fh)
    with patch.object(bok_client, "_bok_session") as session_factory:
        session_factory.return_value.get.return_value.json.return_value = raw
        snapshot = bok_client.fetch_bok_snapshot()
    cache.set(bok_client._cache_key(), snapshot)


@override_settings(BOK_ENABLED_COLLECTIONS=["ui-test"])
class BokLandingPageTests(TestCase):
    def setUp(self):
        _seed_cache()
        self.client = Client()
        self.user = User.objects.create_user(
            username="ui@example.com", email="ui@example.com", password="x"
        )
        self.source = Source.objects.create(name="Src", url_field="https://e.example/oai")
        # Opt-in semantic: editor only shows when work is in an enabled
        # collection. Put the test work in one matching the class-level
        # override.
        self.collection = Collection.objects.create(
            identifier="ui-test", name="UI Test", is_published=True,
        )
        self.work = Work.objects.create(
            title="A harvested work",
            source=self.source,
            status="h",
            creationDate=timezone.now(),
            bok_concepts=["CV"],
        )
        self.work.collections.add(self.collection)

    def test_anonymous_sees_chip_but_no_editor(self):
        # Anonymous viewers can only access published works; flip status.
        self.work.status = "p"
        self.work.save()

        resp = self.client.get(f"/work/{self.work.id}/")
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        self.assertIn("Cartography and Visualization", body)
        self.assertIn("http://bok.eo4geo.eu/CV", body)
        # Editor card is gated behind `can_tag_bok`.
        self.assertNotIn('id="bok-edit-card"', body)

    def test_logged_in_user_on_harvested_work_sees_editor(self):
        self.client.login(username="ui@example.com", password="x")
        resp = self.client.get(f"/work/{self.work.id}/")
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        self.assertIn('id="bok-edit-card"', body)
        self.assertIn('id="bok-search-input"', body)
        self.assertIn('id="bok-suggestions"', body)
        # Initial chip pre-rendered server-side.
        self.assertIn('data-code="CV"', body)
        # JS bootstrap is present.
        self.assertIn("OPTIMAP_BOK", body)

    def test_orphan_code_renders_greyed(self):
        self.work.bok_concepts = ["CV", "REMOVED-CODE"]
        self.work.status = "p"
        self.work.save()
        resp = self.client.get(f"/work/{self.work.id}/")
        body = resp.content.decode()
        self.assertIn("REMOVED-CODE", body)
        self.assertIn("bok-chip-orphan", body)

    def test_chip_displayed_when_no_concepts_is_absent(self):
        self.work.bok_concepts = []
        self.work.status = "p"
        self.work.save()
        resp = self.client.get(f"/work/{self.work.id}/")
        body = resp.content.decode()
        self.assertNotIn('id="bok-topics-display"', body)

    @override_settings(BOK_ENABLED_COLLECTIONS=["alpha"])
    def test_collection_gate_hides_editor_for_work_outside_collection(self):
        Collection.objects.create(identifier="alpha", name="Alpha", is_published=True)
        self.client.login(username="ui@example.com", password="x")
        resp = self.client.get(f"/work/{self.work.id}/")
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        # Editor card hidden — work is not in 'alpha'.
        self.assertNotIn('id="bok-edit-card"', body)
        # Existing chip is still displayed (read-only).
        self.assertIn("Cartography and Visualization", body)

    @override_settings(BOK_ENABLED_COLLECTIONS=["alpha"])
    def test_collection_gate_shows_editor_for_work_in_enabled_collection(self):
        alpha = Collection.objects.create(identifier="alpha", name="Alpha", is_published=True)
        self.work.collections.add(alpha)
        self.client.login(username="ui@example.com", password="x")
        resp = self.client.get(f"/work/{self.work.id}/")
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        self.assertIn('id="bok-edit-card"', body)

    def test_missing_info_alert_links_to_bok_editor(self):
        """When BoK topics are missing on an eligible work, the
        missing-information alert lists "topics (EO4GEO BoK)" as an
        anchor link to the BoK editor card."""
        self.work.bok_concepts = []
        self.work.save()
        self.client.login(username="ui@example.com", password="x")
        resp = self.client.get(f"/work/{self.work.id}/")
        body = resp.content.decode()
        self.assertIn('Missing information', body)
        self.assertIn('href="#bok-edit-card"', body)
        self.assertIn('topics (EO4GEO BoK)', body)
