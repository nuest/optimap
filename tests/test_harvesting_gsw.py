# SPDX-FileCopyrightText: 2026 OPTIMETA and KOMET projects <https://projects.tib.eu/komet>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests for the GeoScienceWorld harvester (issue #251)."""

import os
from unittest.mock import MagicMock, patch

import django
from django.test import TestCase, override_settings, tag

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "optimap.settings")
django.setup()

from django.contrib.gis.geos import GeometryCollection

from works.harvesting.geoscienceworld import (
    _geom_from_geoextent_result,
    parse_gsw_response_and_save_works,
)
from works.models import HarvestingEvent, Source, Work


def _make_source(doi_prefix="10.1190"):
    return Source.objects.create(
        name=f"GSW Test Source ({doi_prefix})",
        url_field="https://pubs.geoscienceworld.org/test",
        source_type="geoscienceworld",
        doi_prefix=doi_prefix,
        default_work_type="article",
        harvest_interval_minutes=0,
    )


class GeomFromGeoextentResultTest(TestCase):
    """Unit tests for _geom_from_geoextent_result."""

    def test_none_input_returns_empty_collection(self):
        result = _geom_from_geoextent_result(None)
        self.assertIsInstance(result, GeometryCollection)
        self.assertTrue(result.empty)

    def test_empty_dict_returns_empty_collection(self):
        result = _geom_from_geoextent_result({})
        self.assertIsInstance(result, GeometryCollection)
        self.assertTrue(result.empty)

    def test_point_feature(self):
        result = _geom_from_geoextent_result(
            {
                "features": [
                    {
                        "type": "Feature",
                        "geometry": {"type": "Point", "coordinates": [-104.5, 38.2]},
                        "properties": {},
                    }
                ]
            }
        )
        self.assertIsInstance(result, GeometryCollection)
        self.assertFalse(result.empty)
        self.assertEqual(len(result), 1)
        geom = result[0]
        self.assertEqual(geom.geom_type, "Point")
        self.assertAlmostEqual(geom.x, -104.5)
        self.assertAlmostEqual(geom.y, 38.2)

    def test_polygon_feature(self):
        coords = [[-105.0, 37.0], [-103.0, 37.0], [-103.0, 39.0], [-105.0, 39.0], [-105.0, 37.0]]
        result = _geom_from_geoextent_result(
            {
                "features": [
                    {
                        "type": "Feature",
                        "geometry": {"type": "Polygon", "coordinates": [coords]},
                        "properties": {},
                    }
                ]
            }
        )
        self.assertFalse(result.empty)
        self.assertEqual(result[0].geom_type, "Polygon")

    def test_multiple_features_collected(self):
        result = _geom_from_geoextent_result(
            {
                "features": [
                    {"type": "Feature", "geometry": {"type": "Point", "coordinates": [10.0, 50.0]}, "properties": {}},
                    {"type": "Feature", "geometry": {"type": "Point", "coordinates": [20.0, 60.0]}, "properties": {}},
                ]
            }
        )
        self.assertEqual(len(result), 2)

    def test_null_geometry_feature_skipped(self):
        result = _geom_from_geoextent_result(
            {
                "features": [
                    {"type": "Feature", "geometry": None, "properties": {}},
                ]
            }
        )
        self.assertTrue(result.empty)

    def test_malformed_geometry_skipped(self):
        result = _geom_from_geoextent_result(
            {
                "features": [
                    {"type": "Feature", "geometry": {"type": "NotAType", "coordinates": []}, "properties": {}},
                ]
            }
        )
        self.assertTrue(result.empty)


CROSSREF_PAGE = {
    "message": {
        "items": [
            {
                "DOI": "10.1190/geo2020-0528.1",
                "title": ["Diagenesis and pore-pressure induced dim spots"],
                "abstract": "<jats:p>A study of dim spots near the Jurassic horizon.</jats:p>",
                "URL": "https://doi.org/10.1190/geo2020-0528.1",
                "published-print": {"date-parts": [[2021, 3, 1]]},
                "author": [{"given": "Alice", "family": "Smith"}],
                "volume": "86",
                "issue": "2",
                "page": "1-10",
            }
        ],
        "next-cursor": None,
    }
}

GEOEXTENT_RESULT = {
    "features": [
        {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [-104.5, 38.2]},
            "properties": {"source": "GeoScienceWorld"},
        }
    ],
    "bbox": [38.2, -104.5, 38.2, -104.5],
    "crs": "EPSG:4326",
}


class ParseGswResponseTest(TestCase):
    """Integration tests for parse_gsw_response_and_save_works with mocked HTTP and geoextent."""

    def setUp(self):
        self.source = _make_source("10.1190")
        self.event = HarvestingEvent.objects.create(source=self.source, status="in_progress")

    @patch("works.harvesting.geoscienceworld.geoextent_lib.from_remote")
    @patch("works.harvesting.geoscienceworld._crossref_session")
    def test_work_created_with_geometry(self, mock_session_fn, mock_from_remote):
        session = MagicMock()
        mock_session_fn.return_value = session
        session.get.return_value.ok = True
        session.get.return_value.json.return_value = CROSSREF_PAGE

        mock_from_remote.return_value = GEOEXTENT_RESULT

        saved, seen = parse_gsw_response_and_save_works(
            self.source,
            self.event,
            "10.1190",
            max_records=1,
            throttle=0,
        )

        self.assertEqual(saved, 1)
        self.assertEqual(seen, 1)

        work = Work.objects.get(doi="10.1190/geo2020-0528.1")
        self.assertEqual(work.title, "Diagenesis and pore-pressure induced dim spots")
        self.assertEqual(str(work.publicationDate), "2021-03-01")
        self.assertFalse(work.geometry.empty)
        self.assertEqual(work.geometry[0].geom_type, "Point")
        self.assertAlmostEqual(work.geometry[0].x, -104.5)
        self.assertEqual(work.provenance["harvest"]["harvester"], "harvest_geoscienceworld")
        self.assertEqual(work.provenance["harvest"]["doi_prefix"], "10.1190")
        self.assertEqual(work.provenance["metadata_sources"]["geometry"], "geoextent_gsw")

    @patch("works.harvesting.geoscienceworld.geoextent_lib.from_remote")
    @patch("works.harvesting.geoscienceworld._crossref_session")
    def test_work_created_without_geometry_on_geoextent_failure(self, mock_session_fn, mock_from_remote):
        session = MagicMock()
        mock_session_fn.return_value = session
        session.get.return_value.ok = True
        session.get.return_value.json.return_value = CROSSREF_PAGE

        mock_from_remote.side_effect = Exception("Cloudflare blocked")

        saved, seen = parse_gsw_response_and_save_works(
            self.source,
            self.event,
            "10.1190",
            max_records=1,
            throttle=0,
        )

        self.assertEqual(saved, 1)
        work = Work.objects.get(doi="10.1190/geo2020-0528.1")
        self.assertTrue(work.geometry.empty)
        self.assertNotIn("geometry", work.provenance["metadata_sources"])

    @patch("works.harvesting.geoscienceworld.geoextent_lib.from_remote")
    @patch("works.harvesting.geoscienceworld._crossref_session")
    def test_no_duplicate_on_second_harvest(self, mock_session_fn, mock_from_remote):
        session = MagicMock()
        mock_session_fn.return_value = session
        session.get.return_value.ok = True
        session.get.return_value.json.return_value = CROSSREF_PAGE
        mock_from_remote.return_value = GEOEXTENT_RESULT

        parse_gsw_response_and_save_works(
            self.source,
            self.event,
            "10.1190",
            max_records=1,
            throttle=0,
        )
        event2 = HarvestingEvent.objects.create(source=self.source, status="in_progress")
        saved2, _ = parse_gsw_response_and_save_works(
            self.source,
            event2,
            "10.1190",
            max_records=1,
            throttle=0,
        )
        self.assertEqual(saved2, 0)
        self.assertEqual(Work.objects.filter(doi="10.1190/geo2020-0528.1").count(), 1)

    @patch("works.harvesting.geoscienceworld.geoextent_lib.from_remote")
    @patch("works.harvesting.geoscienceworld._crossref_session")
    def test_geoextent_skipped_for_existing_work(self, mock_session_fn, mock_from_remote):
        """Second harvest must not call geoextent (or sleep) for already-harvested DOIs."""
        session = MagicMock()
        mock_session_fn.return_value = session
        session.get.return_value.ok = True
        session.get.return_value.json.return_value = CROSSREF_PAGE
        mock_from_remote.return_value = GEOEXTENT_RESULT

        parse_gsw_response_and_save_works(
            self.source,
            self.event,
            "10.1190",
            max_records=1,
            throttle=0,
        )
        self.assertEqual(mock_from_remote.call_count, 1)

        event2 = HarvestingEvent.objects.create(source=self.source, status="in_progress")
        with patch("works.harvesting.geoscienceworld.time.sleep") as mock_sleep:
            parse_gsw_response_and_save_works(
                self.source,
                event2,
                "10.1190",
                max_records=1,
                throttle=2,
            )
            mock_sleep.assert_not_called()
        # geoextent not called a second time
        self.assertEqual(mock_from_remote.call_count, 1)

    @override_settings(GEOSCIENCEWORLD_THROTTLE_SECONDS=0)
    @patch("works.harvesting.geoscienceworld.geoextent_lib.from_remote")
    @patch("works.harvesting.geoscienceworld._crossref_session")
    def test_throttle_setting_respected(self, mock_session_fn, mock_from_remote):
        session = MagicMock()
        mock_session_fn.return_value = session
        session.get.return_value.ok = True
        session.get.return_value.json.return_value = CROSSREF_PAGE
        mock_from_remote.return_value = {}

        with patch("works.harvesting.geoscienceworld.time.sleep") as mock_sleep:
            parse_gsw_response_and_save_works(
                self.source,
                self.event,
                "10.1190",
                max_records=1,
                throttle=0,
            )
            mock_sleep.assert_not_called()


@tag("online")
class GswOnlineTest(TestCase):
    """Live integration test against GeoScienceWorld via geoextent.

    Requires network access. Tests a known SEG DOI that has GeoRef coordinates.
    Self-skips if the GSW endpoint is unreachable.
    """

    KNOWN_DOI = "10.1190/tle44120952.1"

    def _skip_if_unreachable(self):
        try:
            import geoextent.lib.extent as geoextent_lib  # noqa: F401
        except ImportError:
            self.skipTest("geoextent not installed")
        try:
            from curl_cffi import requests as cffi_requests

            cffi_requests.head("https://pubs.geoscienceworld.org/", impersonate="chrome", timeout=10)
        except Exception:
            self.skipTest("GeoScienceWorld unreachable")

    def test_known_doi_yields_geometry(self):
        """A known SEG article with GeoRef coordinates should produce a non-empty GeometryCollection."""
        self._skip_if_unreachable()

        import geoextent.lib.extent as geoextent_lib

        try:
            result = geoextent_lib.from_remote(self.KNOWN_DOI, bbox=True)
        except Exception as e:
            self.skipTest(
                f"geoextent could not resolve DOI {self.KNOWN_DOI} "
                f"(may require DOI redirect to pubs.geoscienceworld.org): {e}"
            )

        geom = _geom_from_geoextent_result(result)
        self.assertIsInstance(geom, GeometryCollection)
        self.assertFalse(
            geom.empty,
            f"Expected coordinates for DOI {self.KNOWN_DOI} but got empty geometry. geoextent result: {result}",
        )
