# SPDX-FileCopyrightText: 2022 OPTIMETA and KOMET projects <https://projects.tib.eu/komet>
# SPDX-License-Identifier: GPL-3.0-or-later

from bs4 import BeautifulSoup
from django.test import TestCase

from works.tasks import extract_geometry_from_html, extract_timeperiod_from_html


class SimpleTest(TestCase):
    def test_parse_geometry(self):
        html_doc = """
        <meta name="DC.Coverage" xml:lang="en" content="Earth, Europe, Republic of France, Pays de la Loire"/>
        <meta name="DC.SpatialCoverage" scheme="GeoJSON" content="{&quot;type&quot;:&quot;FeatureCollection&quot;,&quot;features&quot;:[{&quot;type&quot;:&quot;Feature&quot;,&quot;properties&quot;:{&quot;provenance&quot;:{&quot;description&quot;:&quot;geometric shape created by user (drawing)&quot;,&quot;id&quot;:11}},&quot;geometry&quot;:{&quot;type&quot;:&quot;LineString&quot;,&quot;coordinates&quot;:[[0.19995063543319705,47.83528342275264],[-0.6350103020668031,47.80577611936812]]}}],&quot;administrativeUnits&quot;:[{&quot;name&quot;:&quot;Earth&quot;,&quot;geonameId&quot;:6295630,&quot;bbox&quot;:&quot;not available&quot;,&quot;administrativeUnitSuborder&quot;:[&quot;Earth&quot;],&quot;provenance&quot;:{&quot;description&quot;:&quot;administrative unit created by user (acceppting the suggestion of the geonames API , which was created on basis of a geometric shape input)&quot;,&quot;id&quot;:23}},{&quot;name&quot;:&quot;Europe&quot;,&quot;geonameId&quot;:6255148,&quot;bbox&quot;:{&quot;east&quot;:41.73303985595703,&quot;south&quot;:27.6377894797159,&quot;north&quot;:80.76416015625,&quot;west&quot;:-24.532675386662543},&quot;administrativeUnitSuborder&quot;:[&quot;Earth&quot;,&quot;Europe&quot;],&quot;provenance&quot;:{&quot;description&quot;:&quot;administrative unit created by user (acceppting the suggestion of the geonames API , which was created on basis of a geometric shape input)&quot;,&quot;id&quot;:23}},{&quot;name&quot;:&quot;Republic of France&quot;,&quot;geonameId&quot;:3017382,&quot;bbox&quot;:{&quot;east&quot;:9.56009360694225,&quot;south&quot;:41.3335556861592,&quot;north&quot;:51.0889894407743,&quot;west&quot;:-5.14127657354623},&quot;administrativeUnitSuborder&quot;:[&quot;Earth&quot;,&quot;Europe&quot;,&quot;Republic of France&quot;],&quot;provenance&quot;:{&quot;description&quot;:&quot;administrative unit created by user (acceppting the suggestion of the geonames API , which was created on basis of a geometric shape input)&quot;,&quot;id&quot;:23}},{&quot;name&quot;:&quot;Pays de la Loire&quot;,&quot;geonameId&quot;:2988289,&quot;bbox&quot;:{&quot;east&quot;:0.916650657911376,&quot;south&quot;:46.2666616230696,&quot;north&quot;:48.5679940644253,&quot;west&quot;:-2.62573947290169},&quot;administrativeUnitSuborder&quot;:[&quot;Earth&quot;,&quot;Europe&quot;,&quot;Republic of France&quot;,&quot;Pays de la Loire&quot;],&quot;provenance&quot;:{&quot;description&quot;:&quot;administrative unit created by user (acceppting the suggestion of the geonames API , which was created on basis of a geometric shape input)&quot;,&quot;id&quot;:23}}],&quot;temporalProperties&quot;:{&quot;unixDateRange&quot;:&quot;[1654041600000,1654214399000]&quot;,&quot;provenance&quot;:{&quot;description&quot;:&quot;temporal properties created by user&quot;,&quot;id&quot;:31}}}" />
        <meta name="geo.placename" content="Pays de la Loire" />
        <meta name="DC.box" content="name=Pays de la Loire; northlimit=48.567994064425; southlimit=46.26666162307; westlimit=-2.6257394729017; eastlimit=0.91665065791138; projection=EPSG3857" />
        <meta name="ISO 19139" content="<gmd:EX_GeographicBoundingBox><gmd:westBoundLongitude><gco:Decimal>-2.6257394729017</gco:Decimal></gmd:westBoundLongitude><gmd:eastBoundLongitude><gco:Decimal>0.91665065791138</gco:Decimal></gmd:eastBoundLongitude><gmd:southBoundLatitude><gco:Decimal>46.26666162307</gco:Decimal></gmd:southBoundLatitude><gmd:northBoundLatitude><gco:Decimal>48.567994064425</gco:Decimal></gmd:northBoundLatitude></gmd:EX_GeographicBoundingBox>" />
        """

        soup = BeautifulSoup(html_doc, "html.parser")
        geom_object, source_label = extract_geometry_from_html(soup)
        self.assertEqual(geom_object.geom_type, "GeometryCollection")
        self.assertEqual(geom_object.num_geom, 1)
        self.assertEqual(geom_object[0].geom_type, "LineString")
        self.assertEqual(geom_object[0].num_points, 2)
        # The DC.SpatialCoverage GeoJSON path should be the labelled source.
        self.assertEqual(source_label, "DC.SpatialCoverage")

    def test_parse_time(self):
        html_doc = """
        <meta name="DC.Coverage" xml:lang="en" content="Earth, Europe, Republic of France, Pays de la Loire"/>
        <meta name="DC.temporal" scheme="ISO8601" content="2022-06-01/2022-06-08" />
        <meta name="DC.PeriodOfTime" scheme="ISO8601" content="2023-06-01/2023-06-08" />
        """

        soup = BeautifulSoup(html_doc, "html.parser")
        period_start, period_end = extract_timeperiod_from_html(soup)
        self.assertEqual(period_start, ["2022-06-01"])
        self.assertEqual(period_end, ["2022-06-08"])

        html_doc = """
        <meta name="DC.Coverage" xml:lang="en" content="Earth, Europe, Republic of France, Pays de la Loire"/>
        <meta name="DC.PeriodOfTime" scheme="ISO8601" content="2023-06-01/2023-06-08" />
        """

        soup = BeautifulSoup(html_doc, "html.parser")
        period_start, period_end = extract_timeperiod_from_html(soup)
        self.assertEqual(period_start, ["2023-06-01"])
        self.assertEqual(period_end, ["2023-06-08"])

    def test_content_location_single_point(self):
        html_doc = """
        <script type="application/ld+json">
        {"@type": "ScholarlyArticle",
         "contentLocation": {"@type": "GeoCoordinates", "latitude": 60.17, "longitude": 24.94}}
        </script>
        """
        soup = BeautifulSoup(html_doc, "html.parser")
        geom, label = extract_geometry_from_html(soup)
        self.assertIsNotNone(geom)
        self.assertEqual(label, "schema.org contentLocation")
        self.assertEqual(geom.geom_type, "GeometryCollection")
        self.assertEqual(geom.num_geom, 1)
        self.assertEqual(geom[0].geom_type, "Point")
        self.assertAlmostEqual(geom[0].x, 24.94, places=5)
        self.assertAlmostEqual(geom[0].y, 60.17, places=5)

    def test_content_location_multiple_points(self):
        html_doc = """
        <script type="application/ld+json">
        {"@type": "ScholarlyArticle",
         "contentLocation": [
           {"@type": "GeoCoordinates", "latitude": 51.5, "longitude": -0.1},
           {"@type": "GeoCoordinates", "latitude": 48.8, "longitude": 2.35}
         ]}
        </script>
        """
        soup = BeautifulSoup(html_doc, "html.parser")
        geom, label = extract_geometry_from_html(soup)
        self.assertIsNotNone(geom)
        self.assertEqual(label, "schema.org contentLocation")
        self.assertEqual(geom.geom_type, "GeometryCollection")
        self.assertEqual(geom.num_geom, 2)

    def test_content_location_place_with_geo(self):
        # Pensoft/ARPHA sometimes wraps coordinates in a Place with a geo sub-property.
        html_doc = """
        <script type="application/ld+json">
        {"@type": "ScholarlyArticle",
         "contentLocation": {
           "@type": "Place",
           "geo": {"@type": "GeoCoordinates", "latitude": -33.87, "longitude": 151.21}
         }}
        </script>
        """
        soup = BeautifulSoup(html_doc, "html.parser")
        geom, label = extract_geometry_from_html(soup)
        self.assertIsNotNone(geom)
        self.assertEqual(label, "schema.org contentLocation")
        self.assertEqual(geom.num_geom, 1)
        self.assertEqual(geom[0].geom_type, "Point")
        self.assertAlmostEqual(geom[0].x, 151.21, places=5)

    def test_content_location_priority_below_spatial_coverage(self):
        # spatialCoverage must win over contentLocation when both are present.
        html_doc = """
        <script type="application/ld+json">
        {"@type": "ScholarlyArticle",
         "spatialCoverage": {"geo": {"@type": "GeoShape", "box": "10 20 30 40"}},
         "contentLocation": {"@type": "GeoCoordinates", "latitude": 5.0, "longitude": 5.0}}
        </script>
        """
        soup = BeautifulSoup(html_doc, "html.parser")
        geom, label = extract_geometry_from_html(soup)
        self.assertEqual(label, "schema.org JSON-LD")
        self.assertEqual(geom[0].geom_type, "Polygon")

    def test_content_location_rejects_projected_coordinates(self):
        """GeoCoordinates with projected (non-WGS84) values must be silently dropped.

        Some BDJ articles mix valid decimal-degree points with UTM/projected
        coordinates (values in the millions) in the same contentLocation block.
        Only the valid WGS84 points should end up in the geometry.
        """
        html_doc = """
        <script type="application/ld+json">
        {"@type": "ScholarlyArticle",
         "contentLocation": {"@type": "Place", "geo": [
           {"@type": "GeoCoordinates", "latitude": 781272.6, "longitude": 2373393.7},
           {"@type": "GeoCoordinates", "latitude": 21.441017, "longitude": -90.286299},
           {"@type": "GeoCoordinates", "latitude": 780535.1, "longitude": 2373588.2}
         ]}}
        </script>
        """
        soup = BeautifulSoup(html_doc, "html.parser")
        geom, label = extract_geometry_from_html(soup)
        self.assertEqual(label, "schema.org contentLocation")
        self.assertEqual(geom.num_geom, 1)
        self.assertAlmostEqual(geom[0].x, -90.286299, places=4)
        self.assertAlmostEqual(geom[0].y, 21.441017, places=4)

    def test_content_location_missing(self):
        html_doc = """
        <meta name="DC.Identifier.pageNumber" content="1-2"/>
        <meta name="DC.Identifier.URI" content="https://journal.com/index.php/josis/article/view/1"/>
        <meta name="DC.Language" scheme="ISO639-1" content="en"/>
        """

        soup = BeautifulSoup(html_doc, "html.parser")
        geom_object, source_label = extract_geometry_from_html(soup)
        period_start, period_end = extract_timeperiod_from_html(soup)
        self.assertIsNone(geom_object)
        self.assertIsNone(source_label)
        self.assertEqual(period_start, [None])
        self.assertEqual(period_end, [None])
