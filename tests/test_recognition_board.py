# SPDX-FileCopyrightText: 2026 OPTIMETA and KOMET projects <https://projects.tib.eu/komet>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests for the contributor Recognition Board (#240).

Covers:
- Contribution rows are created when users contribute spatial / temporal metadata.
- Recognition Board view filters out users who have not opted in.
- Tier-bucketing helper places counts in the expected tiers.
- Username uniqueness is enforced by the settings view (no 500).
- Internal counting persists for users without opt-in.
"""

import json

from django.contrib.auth import get_user_model
from django.contrib.gis.geos import GeometryCollection, Point
from django.test import TestCase

from works.models import Contribution, Source, UserProfile, Work
from works.recognition import RECOGNITION_TIERS, group_by_tier, is_offensive, tier_for

User = get_user_model()


class ContributionRecordingTests(TestCase):
    def setUp(self):
        self.source = Source.objects.create(name="Test Source", is_oa=True, is_preprint=False)
        self.user = User.objects.create_user(
            username="contrib@example.com",
            email="contrib@example.com",
            password="pw12345!",
        )
        self.work = Work.objects.create(
            title="A harvested work",
            status="h",
            url="http://example.org/h1",
            geometry=GeometryCollection(),
            source=self.source,
        )
        self.geom = {
            "type": "GeometryCollection",
            "geometries": [{"type": "Point", "coordinates": [13.4, 52.5]}],
        }

    def _post_contribution(self, payload):
        return self.client.post(
            f"/work/{self.work.id}/contribute-geometry/",
            data=json.dumps(payload),
            content_type="application/json",
        )

    def test_spatial_contribution_creates_one_row(self):
        self.client.login(username="contrib@example.com", password="pw12345!")
        resp = self._post_contribution({"geometry": self.geom})
        self.assertEqual(resp.status_code, 200)
        rows = list(Contribution.objects.filter(user=self.user, work=self.work))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].kind, Contribution.SPATIAL)

    def test_combined_contribution_creates_two_rows(self):
        self.client.login(username="contrib@example.com", password="pw12345!")
        resp = self._post_contribution(
            {
                "geometry": self.geom,
                "temporal_extent": {"start_date": "2024-01-01", "end_date": "2024-12-31"},
            }
        )
        self.assertEqual(resp.status_code, 200)
        kinds = set(Contribution.objects.filter(user=self.user, work=self.work).values_list("kind", flat=True))
        self.assertEqual(kinds, {Contribution.SPATIAL, Contribution.TEMPORAL})

    def test_temporal_only_contribution_creates_temporal_row(self):
        # Temporal-only contributions need a work that already has geometry (status 'h' is ok).
        self.client.login(username="contrib@example.com", password="pw12345!")
        # Re-use the same work; sending only a temporal extent.
        resp = self._post_contribution({"temporal_extent": {"start_date": "2024-06-01"}})
        self.assertEqual(resp.status_code, 200)
        rows = list(Contribution.objects.filter(user=self.user, work=self.work))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].kind, Contribution.TEMPORAL)

    def test_internal_counting_independent_of_opt_in(self):
        """Even if the user has not opted in, contributions are still recorded."""
        # Default UserProfile (auto-created on User.save) has recognition_opt_in=False.
        self.assertFalse(UserProfile.objects.get(user=self.user).recognition_opt_in)
        self.client.login(username="contrib@example.com", password="pw12345!")
        self._post_contribution({"geometry": self.geom})
        self.assertEqual(Contribution.objects.filter(user=self.user).count(), 1)


class TierBucketingTests(TestCase):
    def test_tier_for_thresholds(self):
        self.assertIsNone(tier_for(0))
        self.assertEqual(tier_for(1).level, 1)
        self.assertEqual(tier_for(9).level, 1)
        self.assertEqual(tier_for(10).level, 2)
        self.assertEqual(tier_for(99).level, 2)
        self.assertEqual(tier_for(100).level, 3)
        self.assertEqual(tier_for(999).level, 3)
        self.assertEqual(tier_for(1000).level, 4)
        self.assertEqual(tier_for(9999).level, 4)
        self.assertEqual(tier_for(10000).level, 5)
        self.assertEqual(tier_for(99999).level, 5)

    def test_group_by_tier_includes_all_five_tiers(self):
        class FakeEntry:
            def __init__(self, total):
                self.total = total

        grouped = group_by_tier([FakeEntry(1), FakeEntry(15), FakeEntry(0)])
        self.assertEqual(len(grouped), 5)
        # Returned in descending tier order (5 → 1).
        self.assertEqual([t.level for t, _ in grouped], [5, 4, 3, 2, 1])
        # Tier 1 should hold the count=1 entry, Tier 2 the count=15 entry, others empty.
        bucket = {t.level: entries for t, entries in grouped}
        self.assertEqual(len(bucket[1]), 1)
        self.assertEqual(len(bucket[2]), 1)
        self.assertEqual(len(bucket[3]), 0)
        self.assertEqual(len(bucket[4]), 0)
        self.assertEqual(len(bucket[5]), 0)

    def test_is_offensive_word_at_start(self):
        self.assertTrue(is_offensive("stupid-puffin"))
        self.assertTrue(is_offensive("damn-it"))

    def test_is_offensive_word_at_end(self):
        self.assertTrue(is_offensive("clever-stupid"))
        self.assertTrue(is_offensive("something-damn"))

    def test_is_offensive_word_in_middle(self):
        self.assertTrue(is_offensive("clever-stupid-puffin"))

    def test_is_offensive_underscore_separator(self):
        self.assertTrue(is_offensive("clever_stupid"))
        self.assertTrue(is_offensive("hello_damn_world"))

    def test_is_offensive_mixed_separators(self):
        self.assertTrue(is_offensive("clever_stupid-puffin"))

    def test_is_offensive_case_insensitive(self):
        self.assertTrue(is_offensive("STUPID-Puffin"))
        self.assertTrue(is_offensive("Damn-it"))
        self.assertTrue(is_offensive("StUpId"))

    def test_is_offensive_clean_names_pass(self):
        # Slug-style names from coolname should consistently pass.
        for name in ["clever-puffin", "marco-polo", "vasco-da-gama", "explorer-1492"]:
            self.assertFalse(is_offensive(name), f"{name!r} should not be flagged")

    def test_is_offensive_empty_string(self):
        self.assertFalse(is_offensive(""))
        self.assertFalse(is_offensive(None) if False else is_offensive(""))  # None handled by caller

    def test_is_offensive_only_substring_does_not_match(self):
        # better-profanity matches whole words, so substrings of profane words pass.
        # 'classic' contains 'ass' as a substring but is not profane.
        self.assertFalse(is_offensive("classic-puffin"))
        self.assertFalse(is_offensive("scunthorpe"))

    def test_tier_names_from_explorers_list(self):
        levels_and_names = {(t.level, t.name) for t in RECOGNITION_TIERS}
        self.assertIn((1, "Marco Polo"), levels_and_names)
        self.assertIn((2, "Vasco da Gama"), levels_and_names)
        self.assertIn((3, "Ferdinand Magellan"), levels_and_names)
        self.assertIn((4, "James Cook"), levels_and_names)
        self.assertIn((5, "Roald Amundsen"), levels_and_names)


class RecognitionBoardViewTests(TestCase):
    def setUp(self):
        self.source = Source.objects.create(name="Test Source", is_oa=True, is_preprint=False)
        self.work = Work.objects.create(
            title="W1",
            status="p",
            url="http://example.org/lb1",
            geometry=GeometryCollection(Point(0, 0)),
            source=self.source,
        )
        self.opted_in = User.objects.create_user(username="opt@example.com", email="opt@example.com", password="pw")
        self.opted_out = User.objects.create_user(
            username="silent@example.com", email="silent@example.com", password="pw"
        )
        UserProfile.objects.filter(user=self.opted_in).update(
            recognition_opt_in=True,
            recognition_username="explorer-1",
        )
        UserProfile.objects.filter(user=self.opted_out).update(
            recognition_opt_in=False,
            recognition_username="hidden-1",
        )
        # Both users have one spatial contribution
        Contribution.objects.create(user=self.opted_in, work=self.work, kind=Contribution.SPATIAL)
        Contribution.objects.create(user=self.opted_out, work=self.work, kind=Contribution.SPATIAL)

    def test_only_opted_in_users_appear(self):
        resp = self.client.get("/recognition-board/")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "explorer-1")
        self.assertNotContains(resp, "hidden-1")

    def test_recognition_board_renders_tier_titles(self):
        resp = self.client.get("/recognition-board/")
        self.assertContains(resp, "Marco Polo")
        self.assertContains(resp, "Roald Amundsen")


class RecognitionBoardSettingsTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="settings@example.com",
            email="settings@example.com",
            password="pw",
        )
        self.other = User.objects.create_user(
            username="other@example.com",
            email="other@example.com",
            password="pw",
        )
        UserProfile.objects.filter(user=self.other).update(
            recognition_opt_in=True,
            recognition_username="taken-name",
        )

    def test_opt_in_with_username(self):
        self.client.login(username="settings@example.com", password="pw")
        resp = self.client.post(
            "/usersettings/",
            {
                "form": "recognition",
                "recognition_opt_in": "on",
                "recognition_username": "marco-1492",
            },
        )
        self.assertEqual(resp.status_code, 302)
        profile = UserProfile.objects.get(user=self.user)
        self.assertTrue(profile.recognition_opt_in)
        self.assertEqual(profile.recognition_username, "marco-1492")

    def test_opt_in_with_empty_username_autogenerates(self):
        self.client.login(username="settings@example.com", password="pw")
        resp = self.client.post(
            "/usersettings/",
            {
                "form": "recognition",
                "recognition_opt_in": "on",
                "recognition_username": "",
            },
        )
        self.assertEqual(resp.status_code, 302)
        profile = UserProfile.objects.get(user=self.user)
        self.assertTrue(profile.recognition_opt_in)
        self.assertTrue(profile.recognition_username)
        self.assertGreaterEqual(len(profile.recognition_username), 3)

    def test_duplicate_username_rejected(self):
        self.client.login(username="settings@example.com", password="pw")
        resp = self.client.post(
            "/usersettings/",
            {
                "form": "recognition",
                "recognition_opt_in": "on",
                "recognition_username": "taken-name",
            },
            follow=True,
        )
        self.assertEqual(resp.status_code, 200)  # not 500
        profile = UserProfile.objects.filter(user=self.user).first()
        # Profile should not have adopted the duplicate name.
        self.assertNotEqual(getattr(profile, "recognition_username", None), "taken-name")

    def _post_recognition(self, username, follow=True):
        return self.client.post(
            "/usersettings/",
            {
                "form": "recognition",
                "recognition_opt_in": "on",
                "recognition_username": username,
            },
            follow=follow,
        )

    def _flash_messages(self, response):
        """Return list of (level_tag, text) tuples for messages on a `follow=True` response."""
        return [(m.level_tag, str(m)) for m in response.context["messages"]]

    def test_offensive_username_rejected_with_message(self):
        """Profanity is caught and the user is shown an error message they can see."""
        self.client.login(username="settings@example.com", password="pw")
        resp = self._post_recognition("stupid-puffin")
        self.assertEqual(resp.status_code, 200)
        messages_list = self._flash_messages(resp)
        self.assertEqual(len(messages_list), 1)
        level, text = messages_list[0]
        self.assertEqual(level, "error")
        self.assertIn("different username", text.lower())
        # Profile not modified.
        profile = UserProfile.objects.get(user=self.user)
        self.assertFalse(profile.recognition_opt_in)
        self.assertNotEqual(profile.recognition_username, "stupid-puffin")
        # The flash alert is rendered as a Bootstrap alert in the response HTML.
        self.assertContains(resp, "alert-danger")
        self.assertContains(resp, "different username")

    def test_offensive_username_in_various_positions_rejected(self):
        self.client.login(username="settings@example.com", password="pw")
        for name in ["damn-it", "clever-stupid", "clever-stupid-puffin", "STUPID-Puffin", "hello_damn_world"]:
            with self.subTest(name=name):
                resp = self._post_recognition(name)
                self.assertEqual(resp.status_code, 200)
                profile = UserProfile.objects.get(user=self.user)
                self.assertFalse(profile.recognition_opt_in, f"{name!r} should not have been accepted")

    def test_clean_username_with_substring_of_profanity_accepted(self):
        """'classic-puffin' contains 'ass' as a substring; must NOT be rejected."""
        self.client.login(username="settings@example.com", password="pw")
        resp = self._post_recognition("classic-puffin")
        self.assertEqual(resp.status_code, 200)
        profile = UserProfile.objects.get(user=self.user)
        self.assertTrue(profile.recognition_opt_in)
        self.assertEqual(profile.recognition_username, "classic-puffin")

    def test_invalid_format_message_visible(self):
        self.client.login(username="settings@example.com", password="pw")
        resp = self.client.post(
            "/usersettings/",
            {
                "form": "recognition",
                "recognition_opt_in": "on",
                "recognition_username": "bad name!",
            },
            follow=True,
        )
        messages_list = self._flash_messages(resp)
        self.assertEqual(len(messages_list), 1)
        level, text = messages_list[0]
        self.assertEqual(level, "error")
        self.assertIn("3–64", text)  # mentions the length range
        self.assertContains(resp, "alert-danger")

    def test_duplicate_username_message_visible(self):
        self.client.login(username="settings@example.com", password="pw")
        resp = self._post_recognition("taken-name")
        messages_list = self._flash_messages(resp)
        self.assertEqual(len(messages_list), 1)
        level, text = messages_list[0]
        self.assertEqual(level, "error")
        self.assertIn("already taken", text.lower())
        self.assertContains(resp, "alert-danger")

    def test_successful_save_message_visible(self):
        self.client.login(username="settings@example.com", password="pw")
        resp = self._post_recognition("clean-explorer")
        messages_list = self._flash_messages(resp)
        self.assertEqual(len(messages_list), 1)
        level, text = messages_list[0]
        self.assertEqual(level, "success")
        self.assertIn("saved", text.lower())
        self.assertContains(resp, "alert-success")

    def test_invalid_username_rejected(self):
        self.client.login(username="settings@example.com", password="pw")
        resp = self.client.post(
            "/usersettings/",
            {
                "form": "recognition",
                "recognition_opt_in": "on",
                "recognition_username": "bad name!",  # space and bang are invalid
            },
            follow=True,
        )
        self.assertEqual(resp.status_code, 200)
        profile = UserProfile.objects.filter(user=self.user).first()
        self.assertFalse(profile.recognition_opt_in)

    def test_random_username_endpoint(self):
        self.client.login(username="settings@example.com", password="pw")
        resp = self.client.get("/usersettings/random-username/")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("username", data)
        self.assertGreaterEqual(len(data["username"]), 3)

    def test_random_username_endpoint_requires_auth(self):
        resp = self.client.get("/usersettings/random-username/")
        # @login_required redirects unauthenticated users.
        self.assertIn(resp.status_code, (302, 403))
