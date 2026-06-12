# SPDX-FileCopyrightText: 2026 OPTIMETA and KOMET projects <https://projects.tib.eu/komet>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests for the NER-based text extraction endpoint (/api/v1/geoextent/extract-text/)."""

import json
import os
import unittest
from unittest.mock import patch

import requests as _requests
from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings, tag

from works.models import Source, Work

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "optimap.settings")

User = get_user_model()

# Minimal mock return from geoextent.from_text when two places are resolved.
_MOCK_FROM_TEXT_BERLIN_PARIS = {
    "format": "text",
    "geoextent_handler": "handle_text",
    "extraction_method": "ner",
    "ner_model": "en_core_web_sm",
    "ner_gazetteer": "nominatim",
    "place_names": [
        {
            "name": "Berlin",
            "label": "GPE",
            "char_start": 16,
            "char_end": 22,
            "score": 0.99,
            "gazetteer": "nominatim",
            "matched": True,
            "candidate_count": 1,
            "lat": 52.520007,
            "lon": 13.404954,
            "match_name": "Berlin, Deutschland",
            "gazetteer_id": "240109189",
            "gazetteer_url": "https://nominatim.openstreetmap.org/details?osmid=240109189",
        },
        {
            "name": "Paris",
            "label": "GPE",
            "char_start": 27,
            "char_end": 32,
            "score": 0.98,
            "gazetteer": "nominatim",
            "matched": False,
            "candidate_count": 3,  # ambiguous — dropped in strict mode
        },
    ],
    "bbox": [13.404954, 52.520007, 13.404954, 52.520007],
    "crs": "EPSG:4326",
}

# Mock return when from_text finds nothing.
_MOCK_FROM_TEXT_NONE = None

# Mock return when NER ran but no place resolved (e.g. all ambiguous/not found).
_MOCK_FROM_TEXT_NO_SPATIAL = {
    "format": "text",
    "geoextent_handler": "handle_text",
    "extraction_method": "ner",
    "ner_model": "en_core_web_sm",
    "ner_gazetteer": "nominatim",
    "place_names": [
        {
            "name": "Springfield",
            "label": "GPE",
            "char_start": 10,
            "char_end": 21,
            "score": 0.95,
            "gazetteer": "nominatim",
            "matched": False,
            "candidate_count": 5,
        },
    ],
}


def _make_work():
    source = Source.objects.create(
        name="Test Journal",
        url_field="https://example.com/oai",
    )
    return Work.objects.create(
        title="A study on climate change",
        doi="10.9999/test.001",
        source=source,
        status="h",
    )


class ExtractTextEndpointTests(TestCase):
    def setUp(self):
        self.client = Client()

    @patch("works.viewsets.geoextent.from_text", return_value=_MOCK_FROM_TEXT_BERLIN_PARIS)
    def test_valid_text_returns_place_names(self, mock_from_text):
        resp = self.client.post(
            "/api/v1/geoextent/extract-text/",
            data=json.dumps({"text": "Field study in Berlin and Paris"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["type"], "FeatureCollection")
        extraction = body.get("geoextent_extraction", {})
        self.assertIn("place_names", extraction)
        place_names = extraction["place_names"]
        self.assertEqual(len(place_names), 2)
        matched = [p for p in place_names if p["matched"]]
        self.assertEqual(len(matched), 1)
        self.assertEqual(matched[0]["name"], "Berlin")

    @patch("works.viewsets.geoextent.from_text", return_value=_MOCK_FROM_TEXT_BERLIN_PARIS)
    def test_char_offsets_present(self, mock_from_text):
        resp = self.client.post(
            "/api/v1/geoextent/extract-text/",
            data=json.dumps({"text": "Field study in Berlin and Paris"}),
            content_type="application/json",
        )
        body = resp.json()
        place = body["geoextent_extraction"]["place_names"][0]
        self.assertIn("char_start", place)
        self.assertIn("char_end", place)

    def test_empty_text_returns_400(self):
        resp = self.client.post(
            "/api/v1/geoextent/extract-text/",
            data=json.dumps({"text": ""}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_missing_text_field_returns_400(self):
        resp = self.client.post(
            "/api/v1/geoextent/extract-text/",
            data=json.dumps({"gazetteer": "nominatim"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)

    @patch("works.viewsets.geoextent.from_text", return_value=_MOCK_FROM_TEXT_NONE)
    def test_no_matches_returns_empty_feature_collection(self, mock_from_text):
        resp = self.client.post(
            "/api/v1/geoextent/extract-text/",
            data=json.dumps({"text": "Pure mathematics has no geography."}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["type"], "FeatureCollection")
        self.assertEqual(body["features"], [])
        self.assertEqual(body["geoextent_extraction"]["place_names"], [])

    @patch("works.viewsets.geoextent.from_text", return_value=_MOCK_FROM_TEXT_NO_SPATIAL)
    def test_all_ambiguous_returns_empty_features_with_place_names(self, mock_from_text):
        resp = self.client.post(
            "/api/v1/geoextent/extract-text/",
            data=json.dumps({"text": "Observations near Springfield."}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["features"], [])
        place_names = body["geoextent_extraction"]["place_names"]
        self.assertEqual(len(place_names), 1)
        self.assertFalse(place_names[0]["matched"])
        self.assertGreater(place_names[0]["candidate_count"], 1)

    @patch("works.viewsets.geoextent.from_text", return_value=_MOCK_FROM_TEXT_BERLIN_PARIS)
    def test_ner_ambiguity_top_passed_to_geoextent(self, mock_from_text):
        self.client.post(
            "/api/v1/geoextent/extract-text/",
            data=json.dumps({"text": "Study in Berlin and Paris", "ner_ambiguity": "top"}),
            content_type="application/json",
        )
        call_kwargs = mock_from_text.call_args[1]
        self.assertEqual(call_kwargs.get("ner_ambiguity"), "top")

    @patch("works.viewsets.geoextent.from_text", return_value=_MOCK_FROM_TEXT_BERLIN_PARIS)
    def test_invalid_ambiguity_value_returns_400(self, mock_from_text):
        resp = self.client.post(
            "/api/v1/geoextent/extract-text/",
            data=json.dumps({"text": "Study in Berlin", "ner_ambiguity": "invalid"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)

    @patch("works.viewsets.geoextent.from_text", return_value=_MOCK_FROM_TEXT_BERLIN_PARIS)
    def test_gazetteer_passed_to_geoextent(self, mock_from_text):
        self.client.post(
            "/api/v1/geoextent/extract-text/",
            data=json.dumps({"text": "Study in Berlin", "gazetteer": "photon"}),
            content_type="application/json",
        )
        call_kwargs = mock_from_text.call_args[1]
        self.assertEqual(call_kwargs.get("ner_gazetteer"), "photon")

    @override_settings(GEOEXTENT_GEONAMES_USERNAME="")
    def test_geonames_without_username_returns_400(self):
        """GeoNames must be rejected with 400 when no username is configured."""
        resp = self.client.post(
            "/api/v1/geoextent/extract-text/",
            data=json.dumps({"text": "Study in Berlin", "gazetteer": "geonames"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)
        body = resp.json()
        self.assertIn("geonames", str(body).lower())

    @override_settings(GEOEXTENT_GEONAMES_USERNAME="testuser")
    @patch("works.viewsets.geoextent.from_text", return_value=_MOCK_FROM_TEXT_BERLIN_PARIS)
    def test_geonames_with_username_is_accepted(self, mock_from_text):
        """GeoNames must be accepted (and forwarded) when a username is configured."""
        resp = self.client.post(
            "/api/v1/geoextent/extract-text/",
            data=json.dumps({"text": "Study in Berlin", "gazetteer": "geonames"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        call_kwargs = mock_from_text.call_args[1]
        self.assertEqual(call_kwargs.get("ner_gazetteer"), "geonames")


class ProvenanceHintTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="testuser", email="testuser@example.com", password="pass")
        self.client = Client()
        self.client.login(username="testuser", password="pass")
        self.work = _make_work()

    def test_contribution_with_provenance_hint_stored_in_event(self):
        geometry = {
            "type": "GeometryCollection",
            "geometries": [{"type": "Point", "coordinates": [13.4, 52.5]}],
        }
        hint = {
            "source": "ner",
            "ner_model": "en_core_web_sm",
            "ner_gazetteer": "nominatim",
            "place_names": ["Berlin"],
        }
        resp = self.client.post(
            f"/work/{self.work.id}/contribute-geometry/",
            data=json.dumps({"geometry": geometry, "provenance_hint": hint}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        self.work.refresh_from_db()
        events = self.work.provenance.get("events", [])
        self.assertTrue(len(events) > 0)
        last_event = events[-1]
        self.assertEqual(last_event.get("geometry_source", {}).get("source"), "ner")
        self.assertIn("Berlin", last_event["geometry_source"]["place_names"])

    def test_contribution_without_provenance_hint_still_works(self):
        geometry = {
            "type": "GeometryCollection",
            "geometries": [{"type": "Point", "coordinates": [13.4, 52.5]}],
        }
        resp = self.client.post(
            f"/work/{self.work.id}/contribute-geometry/",
            data=json.dumps({"geometry": geometry}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        self.work.refresh_from_db()
        events = self.work.provenance.get("events", [])
        self.assertIsNone(events[-1].get("geometry_source"))


@tag("online")
class ExtractTextOnlineTests(TestCase):
    """Live tests: require spaCy model download and Nominatim access."""

    @classmethod
    def _skip_if_nominatim_unreachable(cls):
        url = "https://nominatim.openstreetmap.org/search"
        try:
            r = _requests.get(
                url,
                params={"q": "Hannover", "format": "json", "limit": "1"},
                timeout=10,
                headers={"User-Agent": "OPTIMAP/test"},
            )
            r.raise_for_status()
            if not r.json():
                raise unittest.SkipTest(
                    "Nominatim returned empty results for Hannover — "
                    "service may be rate-limiting; skipping live NER test"
                )
        except _requests.RequestException as e:
            raise unittest.SkipTest(f"Nominatim unreachable: {e}")

    def setUp(self):
        self.client = Client()

    def test_real_ner_extraction_with_known_place(self):
        self._skip_if_nominatim_unreachable()
        resp = self.client.post(
            "/api/v1/geoextent/extract-text/",
            data=json.dumps(
                {
                    "text": "Fieldwork was conducted in the city of Hannover, Germany.",
                    "gazetteer": "nominatim",
                    "ner_ambiguity": "top",
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["type"], "FeatureCollection")
        place_names = body.get("geoextent_extraction", {}).get("place_names", [])
        matched = [p for p in place_names if p.get("matched")]
        self.assertGreater(len(matched), 0, "Expected at least one matched place for 'Hannover, Germany'")
