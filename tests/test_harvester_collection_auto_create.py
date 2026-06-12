# SPDX-FileCopyrightText: 2026 OPTIMETA and KOMET projects <https://projects.tib.eu/komet>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Generalisation of issue #192: every harvest entry point auto-creates a
``Collection`` for its source on first run if none is pre-assigned. The OAI-PMH
path is covered by ``test_oai_collection_auto_create.py``; this module covers
the Mountain Wetlands and OpenAlex-as-source harvesters that previously
required an admin (or fixture) to pre-seed a Collection.
"""

from unittest.mock import Mock, patch

from django.test import TestCase

from works.models import Collection, Source


class MountainWetlandsAutoCreatesCollectionTests(TestCase):
    def setUp(self):
        self.source = Source.objects.create(
            name="Mountain Wetlands Repository",
            url_field="https://andes.example/api/v1/items/",
            source_type="mountain-wetlands",
        )
        self.assertIsNone(self.source.collection)

    @patch("works.harvesting.mountain_wetlands._mwr_session")
    def test_first_harvest_creates_collection_and_links_source(self, mock_session_factory):
        from works.tasks import harvest_mountain_wetlands

        # Empty page — short-circuit the loop without saving any works.
        fake_response = Mock()
        fake_response.ok = True
        fake_response.status_code = 200
        fake_response.json.return_value = {"count": 0, "data": []}
        mock_session = Mock()
        mock_session.get.return_value = fake_response
        mock_session_factory.return_value = mock_session

        harvest_mountain_wetlands(self.source.id)

        self.source.refresh_from_db()
        self.assertIsNotNone(self.source.collection)
        self.assertEqual(self.source.collection.identifier, "mountain-wetlands-repository")
        self.assertFalse(self.source.collection.is_published)
        self.assertEqual(Collection.objects.count(), 1)

    @patch("works.harvesting.mountain_wetlands._mwr_session")
    def test_preassigned_collection_is_left_alone(self, mock_session_factory):
        from works.tasks import harvest_mountain_wetlands

        preassigned = Collection.objects.create(
            identifier="preassigned-mw",
            name="Pre-assigned MW",
            is_published=True,
        )
        self.source.collection = preassigned
        self.source.save(update_fields=["collection"])

        fake_response = Mock()
        fake_response.ok = True
        fake_response.status_code = 200
        fake_response.json.return_value = {"count": 0, "data": []}
        mock_session = Mock()
        mock_session.get.return_value = fake_response
        mock_session_factory.return_value = mock_session

        harvest_mountain_wetlands(self.source.id)

        self.source.refresh_from_db()
        self.assertEqual(self.source.collection_id, preassigned.id)
        self.source.collection.refresh_from_db()
        self.assertTrue(self.source.collection.is_published)


class OpenalexSourceAutoCreatesCollectionTests(TestCase):
    def setUp(self):
        self.source = Source.objects.create(
            name="AGILE GIScience Series",
            url_field="https://api.openalex.org/sources/S4210203054",
            source_type="openalex",
            openalex_id="S4210203054",
        )
        self.assertIsNone(self.source.collection)

    @patch("works.harvesting.openalex_source.parse_openalex_response_and_save_works")
    def test_first_harvest_creates_collection_and_links_source(self, mock_parser):
        from works.tasks import harvest_openalex_source

        # Skip the API loop entirely — only the wiring around it matters here.
        mock_parser.return_value = (0, 0)

        harvest_openalex_source(self.source.id, max_records=0)

        self.source.refresh_from_db()
        self.assertIsNotNone(self.source.collection)
        self.assertEqual(self.source.collection.identifier, "agile-giscience-series")
        self.assertFalse(self.source.collection.is_published)
        self.assertEqual(Collection.objects.count(), 1)

    @patch("works.harvesting.openalex_source.parse_openalex_response_and_save_works")
    def test_preassigned_collection_is_left_alone(self, mock_parser):
        from works.tasks import harvest_openalex_source

        mock_parser.return_value = (0, 0)
        preassigned = Collection.objects.create(
            identifier="preassigned-agile",
            name="Pre-assigned AGILE",
            is_published=True,
        )
        self.source.collection = preassigned
        self.source.save(update_fields=["collection"])

        harvest_openalex_source(self.source.id, max_records=0)

        self.source.refresh_from_db()
        self.assertEqual(self.source.collection_id, preassigned.id)
        self.source.collection.refresh_from_db()
        self.assertTrue(self.source.collection.is_published)
