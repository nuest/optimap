# SPDX-FileCopyrightText: 2025 OPTIMETA and KOMET projects <https://projects.tib.eu/komet>
# SPDX-License-Identifier: GPL-3.0-or-later

import json

from django.test import TestCase

from works.models import Source, Work
from works.utils.geometry import COORDINATE_PRECISION, annotate_rounded_geometry, round_geojson_coordinates


class RoundGeojsonCoordinatesTests(TestCase):
    def test_rounds_nested_floats(self):
        geojson = {
            "type": "Polygon",
            "coordinates": [[[7.123456789, 51.987654321], [8.0, 52.0]]],
        }
        rounded = round_geojson_coordinates(geojson)
        self.assertEqual(rounded["coordinates"][0][0], [7.12346, 51.98765])
        self.assertEqual(rounded["coordinates"][0][1], [8.0, 52.0])

    def test_leaves_non_float_values_untouched(self):
        geojson = {"type": "Point", "coordinates": [1, 2], "id": "abc"}
        self.assertEqual(round_geojson_coordinates(geojson), geojson)

    def test_custom_precision(self):
        self.assertEqual(round_geojson_coordinates([1.123456], precision=2), [1.12])


class AnnotateRoundedGeometryTests(TestCase):
    def setUp(self):
        source = Source.objects.create(name="Source", url_field="http://example.com")
        self.work = Work.objects.create(
            title="Work with a precise geometry",
            url="http://example.com/work",
            source=source,
            doi="10.0001/precise",
            geometry="GEOMETRYCOLLECTION(POLYGON((7.123456789 51.987654321, 8.123456789 51.987654321, "
            "8.123456789 52.987654321, 7.123456789 51.987654321)))",
        )

    def test_annotation_rounds_coordinates_in_the_database(self):
        annotated = annotate_rounded_geometry(Work.objects.filter(pk=self.work.pk)).get()
        parsed = json.loads(annotated._rounded_geojson)
        self.assertEqual(parsed["type"], "GeometryCollection")
        for coordinate in parsed["geometries"][0]["coordinates"][0]:
            for value in coordinate:
                self.assertEqual(round(value, COORDINATE_PRECISION), value)
                self.assertLessEqual(len(str(value).split(".")[-1]), COORDINATE_PRECISION)

    def test_annotation_matches_python_rounding_for_the_same_geometry(self):
        annotated = annotate_rounded_geometry(Work.objects.filter(pk=self.work.pk)).get()
        db_rounded = json.loads(annotated._rounded_geojson)
        python_rounded = round_geojson_coordinates(json.loads(self.work.geometry.geojson))
        self.assertEqual(db_rounded, python_rounded)
