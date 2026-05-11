# SPDX-FileCopyrightText: 2026 OPTIMETA and KOMET projects <https://projects.tib.eu/komet>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Unit tests for the BoK collection-gate eligibility helper."""

from django.test import TestCase, override_settings
from django.utils import timezone

from works.bok import eligibility
from works.models import Collection, Source, Work


class BokEligibilityTests(TestCase):
    def setUp(self):
        self.source = Source.objects.create(
            name="Src", url_field="https://e.example/oai",
        )
        self.collection_a = Collection.objects.create(
            identifier="alpha", name="Alpha", is_published=True,
        )
        self.collection_b = Collection.objects.create(
            identifier="beta", name="Beta", is_published=True,
        )
        self.work_in_a = Work.objects.create(
            title="In A", source=self.source, status="h",
            creationDate=timezone.now(),
        )
        self.work_in_a.collections.add(self.collection_a)
        self.work_loose = Work.objects.create(
            title="Loose", source=self.source, status="h",
            creationDate=timezone.now(),
        )

    @override_settings(BOK_ENABLED_COLLECTIONS=[])
    def test_empty_allow_list_blocks_every_work(self):
        # Opt-in semantic: empty list -> editor disabled site-wide.
        self.assertFalse(eligibility.is_collection_filter_active())
        self.assertFalse(eligibility.is_work_eligible(self.work_in_a))
        self.assertFalse(eligibility.is_work_eligible(self.work_loose))

    @override_settings(BOK_ENABLED_COLLECTIONS=["alpha"])
    def test_filter_active_restricts_to_listed_collections(self):
        self.assertTrue(eligibility.is_collection_filter_active())
        self.assertTrue(eligibility.is_work_eligible(self.work_in_a))
        self.assertFalse(eligibility.is_work_eligible(self.work_loose))

    @override_settings(BOK_ENABLED_COLLECTIONS=["alpha", "beta"])
    def test_multiple_collections_any_match(self):
        self.work_loose.collections.add(self.collection_b)
        self.assertTrue(eligibility.is_work_eligible(self.work_in_a))
        self.assertTrue(eligibility.is_work_eligible(self.work_loose))

    @override_settings(BOK_ENABLED_COLLECTIONS=["nonexistent-slug"])
    def test_unknown_identifier_blocks_everyone(self):
        self.assertFalse(eligibility.is_work_eligible(self.work_in_a))
        self.assertFalse(eligibility.is_work_eligible(self.work_loose))
