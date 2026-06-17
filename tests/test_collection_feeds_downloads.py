# SPDX-FileCopyrightText: 2026 OPTIMETA and KOMET projects <https://projects.tib.eu/komet>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests for collection-scoped feeds (#248) and download endpoints (#217)."""

import json
import tempfile
import xml.etree.ElementTree as ET

from django.contrib.auth import get_user_model
from django.contrib.gis.geos import GeometryCollection, Point, Polygon
from django.test import TestCase
from django.urls import reverse
from osgeo import ogr

from works.models import Collection, Work
from works.views.data import _unwrap_geometry_collection

User = get_user_model()


# ---------------------------------------------------------------------------
# Shared fixture
# ---------------------------------------------------------------------------


class _CollectionFixtureMixin:
    """setUpTestData shared across feed and download test classes."""

    @classmethod
    def setUpTestData(cls):
        cls.col = Collection.objects.create(
            identifier="test-col",
            name="Test Collection",
            is_published=True,
        )
        cls.hidden = Collection.objects.create(
            identifier="hidden-col",
            name="Hidden Collection",
            is_published=False,
        )
        # Published work with geometry — appears in feeds AND downloads.
        cls.pub_geo = Work.objects.create(
            title="Published with geometry",
            abstract="Some abstract.",
            url="https://example.com/pub",
            doi="10.1234/pub",
            status="p",
            geometry=GeometryCollection(Point(12.4924, 41.8902)),
        )
        cls.pub_geo.collections.add(cls.col)
        # Published work without geometry — appears in downloads but NOT feeds.
        cls.pub_no_geo = Work.objects.create(
            title="Published no geometry",
            url="https://example.com/no-geo",
            doi="10.1234/no-geo",
            status="p",
        )
        cls.pub_no_geo.collections.add(cls.col)
        # Harvested (unpublished) work — must never appear in feeds or downloads.
        cls.harv = Work.objects.create(
            title="Harvested work",
            url="https://example.com/harv",
            doi="10.1234/harv",
            status="h",
            geometry=GeometryCollection(Point(0, 0)),
        )
        cls.harv.collections.add(cls.col)


# ---------------------------------------------------------------------------
# Collection feed tests
# ---------------------------------------------------------------------------


class CollectionFeedTests(_CollectionFixtureMixin, TestCase):
    """Tests for /api/v1/feeds/collection-<slug>.{rss,atom}."""

    def _rss(self, slug="test-col"):
        return f"/api/v1/feeds/collection-{slug}.rss"

    def _atom(self, slug="test-col"):
        return f"/api/v1/feeds/collection-{slug}.atom"

    # --- status codes ---

    def test_rss_200_for_published(self):
        self.assertEqual(self.client.get(self._rss()).status_code, 200)

    def test_atom_200_for_published(self):
        self.assertEqual(self.client.get(self._atom()).status_code, 200)

    def test_rss_404_unknown_slug(self):
        self.assertEqual(self.client.get(self._rss("no-such")).status_code, 404)

    def test_atom_404_unknown_slug(self):
        self.assertEqual(self.client.get(self._atom("no-such")).status_code, 404)

    def test_rss_404_unpublished(self):
        self.assertEqual(self.client.get(self._rss("hidden-col")).status_code, 404)

    def test_atom_404_unpublished(self):
        self.assertEqual(self.client.get(self._atom("hidden-col")).status_code, 404)

    # --- content type ---

    def test_rss_content_type_is_xml(self):
        self.assertIn("xml", self.client.get(self._rss())["Content-Type"])

    def test_atom_content_type_is_xml(self):
        self.assertIn("xml", self.client.get(self._atom())["Content-Type"])

    # --- feed title ---

    def test_rss_title_contains_collection_name(self):
        self.assertIn(b"Test Collection", self.client.get(self._rss()).content)

    def test_atom_title_contains_collection_name(self):
        self.assertIn(b"Test Collection", self.client.get(self._atom()).content)

    # --- item inclusion / exclusion ---

    def test_rss_includes_published_work_with_geometry(self):
        self.assertIn(b"Published with geometry", self.client.get(self._rss()).content)

    def test_atom_includes_published_work_with_geometry(self):
        self.assertIn(b"Published with geometry", self.client.get(self._atom()).content)

    def test_rss_excludes_work_without_geometry(self):
        # Feeds require geometry; the no-geo work must not appear.
        self.assertNotIn(b"Published no geometry", self.client.get(self._rss()).content)

    def test_rss_excludes_unpublished_work(self):
        self.assertNotIn(b"Harvested work", self.client.get(self._rss()).content)

    def test_atom_excludes_unpublished_work(self):
        self.assertNotIn(b"Harvested work", self.client.get(self._atom()).content)

    # --- GeoRSS geometry elements ---

    def test_rss_contains_georss_point(self):
        self.assertIn(b"georss:point", self.client.get(self._rss()).content)

    def test_atom_contains_georss_point(self):
        self.assertIn(b"georss:point", self.client.get(self._atom()).content)

    # --- XML validity ---

    def test_rss_is_valid_xml(self):
        try:
            ET.fromstring(self.client.get(self._rss()).content)
        except ET.ParseError as exc:
            self.fail(f"RSS feed is not valid XML: {exc}")

    def test_atom_is_valid_xml(self):
        try:
            ET.fromstring(self.client.get(self._atom()).content)
        except ET.ParseError as exc:
            self.fail(f"Atom feed is not valid XML: {exc}")

    # --- URL reversal sanity ---

    def test_rss_url_reverses_correctly(self):
        url = reverse("optimap:api-collection-georss", kwargs={"collection_slug": "test-col"})
        self.assertEqual(url, "/api/v1/feeds/collection-test-col.rss")

    def test_atom_url_reverses_correctly(self):
        url = reverse("optimap:api-collection-atom", kwargs={"collection_slug": "test-col"})
        self.assertEqual(url, "/api/v1/feeds/collection-test-col.atom")


# ---------------------------------------------------------------------------
# Collection detail page — feed discovery and download links
# ---------------------------------------------------------------------------


class CollectionDetailFeedLinksTests(_CollectionFixtureMixin, TestCase):
    """Feed autodiscovery and the Feeds & downloads card on collection pages."""

    def _page(self, slug="test-col"):
        return reverse("optimap:collection-page", args=[slug])

    def test_published_page_has_rss_autodiscovery(self):
        body = self.client.get(self._page()).content.decode()
        self.assertIn("application/rss+xml", body)
        self.assertIn("/api/v1/feeds/collection-test-col.rss", body)

    def test_published_page_has_atom_autodiscovery(self):
        body = self.client.get(self._page()).content.decode()
        self.assertIn("application/atom+xml", body)
        self.assertIn("/api/v1/feeds/collection-test-col.atom", body)

    def test_published_page_shows_feeds_and_downloads_card(self):
        body = self.client.get(self._page()).content.decode()
        self.assertIn("Feeds &amp; downloads", body)
        self.assertIn("/api/v1/feeds/collection-test-col.rss", body)
        self.assertIn("/api/v1/feeds/collection-test-col.atom", body)
        self.assertIn("/api/v1/collections/test-col/download/geojson/", body)
        self.assertIn("/api/v1/collections/test-col/download/gpkg/", body)
        self.assertIn("/api/v1/collections/test-col/download/csv/", body)

    def test_unpublished_page_no_feed_or_download_links(self):
        # Admin can view the page; but feeds/downloads would 404, so no links.
        admin = User.objects.create_user(
            username="a@b.c",
            email="a@b.c",
            password="x",
            is_staff=True,
        )
        self.client.force_login(admin)
        body = self.client.get(self._page("hidden-col")).content.decode()
        self.assertNotIn("collection-hidden-col.rss", body)
        self.assertNotIn("Feeds &amp; downloads", body)


# ---------------------------------------------------------------------------
# Collection download tests
# ---------------------------------------------------------------------------


class CollectionDownloadTests(_CollectionFixtureMixin, TestCase):
    """Tests for /api/v1/collections/<slug>/download/{geojson,gpkg,csv}/."""

    def _url(self, fmt, slug="test-col"):
        return reverse(f"optimap:download-collection-{fmt}", args=[slug])

    # --- status codes ---

    def test_geojson_200_for_published(self):
        self.assertEqual(self.client.get(self._url("geojson")).status_code, 200)

    def test_gpkg_200_for_published(self):
        self.assertEqual(self.client.get(self._url("gpkg")).status_code, 200)

    def test_csv_200_for_published(self):
        self.assertEqual(self.client.get(self._url("csv")).status_code, 200)

    def test_geojson_404_unknown_slug(self):
        self.assertEqual(self.client.get(self._url("geojson", "no-such")).status_code, 404)

    def test_gpkg_404_unknown_slug(self):
        self.assertEqual(self.client.get(self._url("gpkg", "no-such")).status_code, 404)

    def test_csv_404_unknown_slug(self):
        self.assertEqual(self.client.get(self._url("csv", "no-such")).status_code, 404)

    def test_geojson_404_unpublished(self):
        self.assertEqual(self.client.get(self._url("geojson", "hidden-col")).status_code, 404)

    def test_gpkg_404_unpublished(self):
        self.assertEqual(self.client.get(self._url("gpkg", "hidden-col")).status_code, 404)

    def test_csv_404_unpublished(self):
        self.assertEqual(self.client.get(self._url("csv", "hidden-col")).status_code, 404)

    # --- content type ---

    def test_geojson_content_type(self):
        self.assertIn("application/geo+json", self.client.get(self._url("geojson"))["Content-Type"])

    def test_gpkg_content_type(self):
        self.assertIn("geopackage", self.client.get(self._url("gpkg"))["Content-Type"])

    def test_csv_content_type(self):
        self.assertIn("text/csv", self.client.get(self._url("csv"))["Content-Type"])

    # --- Content-Disposition filename ---

    def test_geojson_filename(self):
        disp = self.client.get(self._url("geojson"))["Content-Disposition"]
        self.assertIn("optimap_collection_test-col.geojson", disp)

    def test_gpkg_filename(self):
        disp = self.client.get(self._url("gpkg"))["Content-Disposition"]
        self.assertIn("optimap_collection_test-col.gpkg", disp)

    def test_csv_filename(self):
        disp = self.client.get(self._url("csv"))["Content-Disposition"]
        self.assertIn("optimap_collection_test-col.csv", disp)

    # --- GeoJSON content ---

    def test_geojson_is_valid_feature_collection(self):
        data = json.loads(self.client.get(self._url("geojson")).content)
        self.assertEqual(data["type"], "FeatureCollection")
        self.assertIn("features", data)

    def test_geojson_includes_published_work(self):
        body = self.client.get(self._url("geojson")).content.decode()
        self.assertIn("Published with geometry", body)

    def test_geojson_includes_published_work_without_geometry(self):
        # Downloads include all published works; geometry is optional.
        body = self.client.get(self._url("geojson")).content.decode()
        self.assertIn("Published no geometry", body)

    def test_geojson_excludes_unpublished_work(self):
        body = self.client.get(self._url("geojson")).content.decode()
        self.assertNotIn("Harvested work", body)

    # --- GeoPackage / CSV basic sanity ---

    def test_gpkg_body_is_non_empty(self):
        self.assertGreater(len(self.client.get(self._url("gpkg")).content), 0)

    def test_csv_body_is_non_empty(self):
        self.assertGreater(len(self.client.get(self._url("csv")).content), 0)

    # --- cache bypass ---

    def test_now_param_still_returns_200(self):
        resp = self.client.get(self._url("geojson") + "?now")
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.content)
        self.assertEqual(data["type"], "FeatureCollection")


# ---------------------------------------------------------------------------
# Sitemap tests
# ---------------------------------------------------------------------------


class CollectionFeedsDownloadsSitemapTests(TestCase):
    """Tests for sitemap-collection-feeds.xml and sitemap-collection-downloads.xml."""

    @classmethod
    def setUpTestData(cls):
        cls.published = Collection.objects.create(
            identifier="pub",
            name="Published",
            is_published=True,
        )
        cls.hidden = Collection.objects.create(
            identifier="priv",
            name="Private",
            is_published=False,
        )

    def test_collection_feeds_sitemap_200(self):
        resp = self.client.get("/sitemap-collection-feeds.xml")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("xml", resp["Content-Type"])

    def test_collection_downloads_sitemap_200(self):
        resp = self.client.get("/sitemap-collection-downloads.xml")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("xml", resp["Content-Type"])

    def test_feeds_sitemap_contains_rss_url(self):
        body = self.client.get("/sitemap-collection-feeds.xml").content.decode()
        self.assertIn("/api/v1/feeds/collection-pub.rss", body)

    def test_feeds_sitemap_contains_atom_url(self):
        body = self.client.get("/sitemap-collection-feeds.xml").content.decode()
        self.assertIn("/api/v1/feeds/collection-pub.atom", body)

    def test_feeds_sitemap_excludes_unpublished(self):
        body = self.client.get("/sitemap-collection-feeds.xml").content.decode()
        self.assertNotIn("collection-priv.rss", body)
        self.assertNotIn("collection-priv.atom", body)

    def test_downloads_sitemap_contains_geojson_url(self):
        body = self.client.get("/sitemap-collection-downloads.xml").content.decode()
        self.assertIn("/api/v1/collections/pub/download/geojson/", body)

    def test_downloads_sitemap_contains_gpkg_url(self):
        body = self.client.get("/sitemap-collection-downloads.xml").content.decode()
        self.assertIn("/api/v1/collections/pub/download/gpkg/", body)

    def test_downloads_sitemap_contains_csv_url(self):
        body = self.client.get("/sitemap-collection-downloads.xml").content.decode()
        self.assertIn("/api/v1/collections/pub/download/csv/", body)

    def test_downloads_sitemap_excludes_unpublished(self):
        body = self.client.get("/sitemap-collection-downloads.xml").content.decode()
        self.assertNotIn("/collections/priv/download/", body)

    def test_sitemaps_in_index(self):
        body = self.client.get("/sitemap.xml").content.decode()
        self.assertIn("sitemap-collection-feeds.xml", body)
        self.assertIn("sitemap-collection-downloads.xml", body)


# ---------------------------------------------------------------------------
# Collection REST API tests  (/api/v1/collections/)
# ---------------------------------------------------------------------------


class CollectionApiTests(_CollectionFixtureMixin, TestCase):
    """Tests for GET /api/v1/collections/ and /api/v1/collections/<identifier>/."""

    LIST_URL = "/api/v1/collections/"

    def _detail(self, slug):
        return f"/api/v1/collections/{slug}/"

    # --- list ---

    def test_list_200_anonymous(self):
        self.assertEqual(self.client.get(self.LIST_URL).status_code, 200)

    def test_list_contains_published(self):
        data = self.client.get(self.LIST_URL).json()
        identifiers = [c["identifier"] for c in data["results"]]
        self.assertIn("test-col", identifiers)

    def test_list_excludes_unpublished(self):
        data = self.client.get(self.LIST_URL).json()
        identifiers = [c["identifier"] for c in data["results"]]
        self.assertNotIn("hidden-col", identifiers)

    # --- detail ---

    def test_detail_200_for_published(self):
        self.assertEqual(self.client.get(self._detail("test-col")).status_code, 200)

    def test_detail_404_for_unpublished(self):
        self.assertEqual(self.client.get(self._detail("hidden-col")).status_code, 404)

    def test_detail_works_count(self):
        data = self.client.get(self._detail("test-col")).json()
        # pub_geo + pub_no_geo are published; harv is not
        self.assertEqual(data["works_count"], 2)

    def test_detail_feeds_present(self):
        data = self.client.get(self._detail("test-col")).json()
        self.assertIn("rss", data["feeds"])
        self.assertIn("atom", data["feeds"])
        self.assertIn("collection-test-col.rss", data["feeds"]["rss"])
        self.assertIn("collection-test-col.atom", data["feeds"]["atom"])

    def test_detail_downloads_present(self):
        data = self.client.get(self._detail("test-col")).json()
        self.assertIn("geojson", data["downloads"])
        self.assertIn("gpkg", data["downloads"])
        self.assertIn("csv", data["downloads"])
        self.assertIn("/collections/test-col/download/geojson/", data["downloads"]["geojson"])

    def test_detail_collection_url_present(self):
        data = self.client.get(self._detail("test-col")).json()
        self.assertIn("/collections/test-col/", data["collection_url"])

    # --- staff access ---

    def test_staff_sees_unpublished_in_list(self):
        staff = User.objects.create_user("staff_api", "staff@test.com", "pw", is_staff=True)
        self.client.force_login(staff)
        data = self.client.get(self.LIST_URL).json()
        identifiers = [c["identifier"] for c in data["results"]]
        self.assertIn("hidden-col", identifiers)

    def test_staff_can_retrieve_unpublished(self):
        staff = User.objects.create_user("staff_api2", "staff2@test.com", "pw", is_staff=True)
        self.client.force_login(staff)
        self.assertEqual(self.client.get(self._detail("hidden-col")).status_code, 200)

    # --- pagination envelope ---

    def test_list_pagination_envelope(self):
        data = self.client.get(self.LIST_URL).json()
        for key in ("count", "next", "previous", "results"):
            self.assertIn(key, data)
        self.assertIsInstance(data["results"], list)

    # --- 404 for nonexistent identifier ---

    def test_detail_404_for_unknown_identifier(self):
        self.assertEqual(self.client.get(self._detail("does-not-exist")).status_code, 404)

    # --- read-only enforcement ---

    def test_list_post_not_allowed(self):
        self.assertEqual(self.client.post(self.LIST_URL, {}, content_type="application/json").status_code, 405)

    def test_detail_put_not_allowed(self):
        self.assertEqual(
            self.client.put(self._detail("test-col"), {}, content_type="application/json").status_code,
            405,
        )

    def test_detail_delete_not_allowed(self):
        self.assertEqual(self.client.delete(self._detail("test-col")).status_code, 405)

    # --- API root includes collections ---

    def test_api_root_has_collections_link(self):
        data = self.client.get("/api/v1/").json()
        self.assertIn("collections", data)
        self.assertIn("/api/v1/collections/", data["collections"])

    # --- works_count for empty collection ---

    def test_works_count_zero_for_empty_collection(self):
        empty = Collection.objects.create(identifier="empty-col", name="Empty", is_published=True)
        data = self.client.get(self._detail("empty-col")).json()
        self.assertEqual(data["works_count"], 0)
        empty.delete()


# ---------------------------------------------------------------------------
# Unit tests for geometry-unwrapping helper
# ---------------------------------------------------------------------------


class UnwrapGeometryCollectionTests(TestCase):
    """Unit tests for works.views.data._unwrap_geometry_collection."""

    def _point(self):
        return {"type": "Point", "coordinates": [12.0, 41.0]}

    def _polygon(self):
        return {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]]}

    def test_none_passes_through(self):
        self.assertIsNone(_unwrap_geometry_collection(None))

    def test_non_collection_passes_through(self):
        pt = self._point()
        self.assertEqual(_unwrap_geometry_collection(pt), pt)

    def test_polygon_passes_through(self):
        pg = self._polygon()
        self.assertEqual(_unwrap_geometry_collection(pg), pg)

    def test_single_point_unwrapped(self):
        pt = self._point()
        gc = {"type": "GeometryCollection", "geometries": [pt]}
        result = _unwrap_geometry_collection(gc)
        self.assertEqual(result["type"], "Point")
        self.assertEqual(result["coordinates"], pt["coordinates"])

    def test_single_polygon_unwrapped(self):
        pg = self._polygon()
        gc = {"type": "GeometryCollection", "geometries": [pg]}
        result = _unwrap_geometry_collection(gc)
        self.assertEqual(result["type"], "Polygon")

    def test_empty_collection_returns_none(self):
        gc = {"type": "GeometryCollection", "geometries": []}
        self.assertIsNone(_unwrap_geometry_collection(gc))

    def test_two_points_become_multipoint(self):
        pt1 = {"type": "Point", "coordinates": [0.0, 0.0]}
        pt2 = {"type": "Point", "coordinates": [1.0, 1.0]}
        gc = {"type": "GeometryCollection", "geometries": [pt1, pt2]}
        result = _unwrap_geometry_collection(gc)
        self.assertEqual(result["type"], "MultiPoint")
        self.assertEqual(len(result["coordinates"]), 2)

    def test_two_polygons_become_multipolygon(self):
        pg1 = self._polygon()
        pg2 = {"type": "Polygon", "coordinates": [[[5, 5], [6, 5], [6, 6], [5, 5]]]}
        gc = {"type": "GeometryCollection", "geometries": [pg1, pg2]}
        result = _unwrap_geometry_collection(gc)
        self.assertEqual(result["type"], "MultiPolygon")
        self.assertEqual(len(result["coordinates"]), 2)

    def test_mixed_types_stay_as_collection(self):
        gc = {"type": "GeometryCollection", "geometries": [self._point(), self._polygon()]}
        result = _unwrap_geometry_collection(gc)
        self.assertEqual(result["type"], "GeometryCollection")


# ---------------------------------------------------------------------------
# GeoJSON download geometry-type assertions
# ---------------------------------------------------------------------------


class CollectionDownloadGeometryTests(_CollectionFixtureMixin, TestCase):
    """Verify that collection GeoJSON download contains primitive geometry types,
    not bare GeometryCollection wrappers (QGIS rendering regression)."""

    def _geojson(self, slug="test-col"):
        return json.loads(
            self.client.get(reverse("optimap:download-collection-geojson", args=[slug]) + "?now").content
        )

    def test_point_geometry_is_unwrapped(self):
        data = self._geojson()
        geo_types = {f["geometry"]["type"] for f in data["features"] if f.get("geometry") is not None}
        self.assertNotIn(
            "GeometryCollection", geo_types, "GeoJSON export must not contain raw GeometryCollection wrappers"
        )

    def test_point_feature_has_point_type(self):
        data = self._geojson()
        # pub_geo is a single-point GeometryCollection — must unwrap to Point.
        # Django's GeoJSON serializer puts fields directly under `properties`.
        matching = [f for f in data["features"] if f.get("properties", {}).get("doi") == "10.1234/pub"]
        self.assertEqual(len(matching), 1)
        self.assertEqual(matching[0]["geometry"]["type"], "Point")


# ---------------------------------------------------------------------------
# GDAL format validation — collection and global downloads
# ---------------------------------------------------------------------------


def _open_bytes_as_ogr(data, suffix):
    """Write *data* to a named temp file, open it with OGR, return (datasource, path).
    Caller is responsible for closing the datasource and deleting the file."""
    tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
    tmp.write(data)
    tmp.flush()
    tmp.close()
    ds = ogr.Open(tmp.name)
    return ds, tmp.name


class CollectionGdalValidationTests(_CollectionFixtureMixin, TestCase):
    """GDAL-backed format validation for collection download endpoints."""

    def _get_bytes(self, fmt, slug="test-col"):
        url = reverse(f"optimap:download-collection-{fmt}", args=[slug]) + "?now"
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        return resp.content

    # --- GeoJSON ---

    def test_collection_geojson_opens_with_gdal(self):
        ds, path = _open_bytes_as_ogr(self._get_bytes("geojson"), ".geojson")
        try:
            self.assertIsNotNone(ds, "GDAL could not open GeoJSON output")
            self.assertGreater(ds.GetLayerCount(), 0)
        finally:
            ds = None
            import os

            os.unlink(path)

    def test_collection_geojson_no_geometry_collection_type(self):
        data = json.loads(self._get_bytes("geojson"))
        geo_types = {f["geometry"]["type"] for f in data["features"] if f.get("geometry") is not None}
        self.assertNotIn("GeometryCollection", geo_types)

    def test_collection_geojson_feature_count_matches_published(self):
        ds, path = _open_bytes_as_ogr(self._get_bytes("geojson"), ".geojson")
        try:
            layer = ds.GetLayer(0)
            self.assertEqual(layer.GetFeatureCount(), 2)  # pub_geo + pub_no_geo
        finally:
            ds = None
            import os

            os.unlink(path)

    # --- GeoPackage ---

    def test_collection_gpkg_opens_with_gdal(self):
        ds, path = _open_bytes_as_ogr(self._get_bytes("gpkg"), ".gpkg")
        try:
            self.assertIsNotNone(ds, "GDAL could not open GeoPackage output")
            self.assertGreater(ds.GetLayerCount(), 0)
        finally:
            ds = None
            import os

            os.unlink(path)

    def test_collection_gpkg_no_geometry_collection_layer_type(self):
        import os

        data = self._get_bytes("gpkg")
        ds, path = _open_bytes_as_ogr(data, ".gpkg")
        try:
            layer = ds.GetLayer(0)
            geom_type = layer.GetGeomType()
            self.assertNotEqual(
                geom_type,
                ogr.wkbGeometryCollection,
                "GeoPackage layer must not be declared as GEOMETRYCOLLECTION",
            )
        finally:
            ds = None
            os.unlink(path)

    def test_collection_gpkg_feature_count_matches_published(self):
        import os

        ds, path = _open_bytes_as_ogr(self._get_bytes("gpkg"), ".gpkg")
        try:
            layer = ds.GetLayer(0)
            self.assertEqual(layer.GetFeatureCount(), 2)
        finally:
            ds = None
            os.unlink(path)

    def test_collection_gpkg_point_features_have_point_geometry(self):
        import os

        ds, path = _open_bytes_as_ogr(self._get_bytes("gpkg"), ".gpkg")
        try:
            layer = ds.GetLayer(0)
            point_types = {ogr.wkbPoint, ogr.wkbPoint25D, ogr.wkbPointM, ogr.wkbPointZM}
            for feat in layer:
                geom = feat.GetGeometryRef()
                if geom is not None:
                    doi = feat.GetField("doi") if feat.GetFieldIndex("doi") >= 0 else None
                    if doi == "10.1234/pub":
                        self.assertIn(
                            geom.GetGeometryType(), point_types, f"Expected Point type, got {geom.GetGeometryName()}"
                        )
        finally:
            ds = None
            os.unlink(path)


class GlobalDownloadGdalValidationTests(TestCase):
    """GDAL validation for the global /download/geopackage/ endpoint."""

    @classmethod
    def setUpTestData(cls):
        cls.work_pt = Work.objects.create(
            title="Global point work",
            doi="10.1234/global-pt",
            url="https://example.com/gpt",
            status="p",
            geometry=GeometryCollection(Point(13.4, 52.5)),
        )
        cls.work_pg = Work.objects.create(
            title="Global polygon work",
            doi="10.1234/global-pg",
            url="https://example.com/gpg",
            status="p",
            geometry=GeometryCollection(Polygon([(0, 0), (1, 0), (1, 1), (0, 0)])),
        )

    def _get_gpkg_bytes(self):
        resp = self.client.get("/download/geopackage/")
        self.assertEqual(resp.status_code, 200)
        # FileResponse is streaming; regular HttpResponse has .content.
        if hasattr(resp, "streaming_content"):
            return b"".join(resp.streaming_content)
        return resp.content

    def test_global_gpkg_opens_with_gdal(self):
        import os

        ds, path = _open_bytes_as_ogr(self._get_gpkg_bytes(), ".gpkg")
        try:
            self.assertIsNotNone(ds, "GDAL could not open global GeoPackage output")
            self.assertGreater(ds.GetLayerCount(), 0)
        finally:
            ds = None
            os.unlink(path)

    def test_global_gpkg_no_geometry_collection_layer_type(self):
        import os

        ds, path = _open_bytes_as_ogr(self._get_gpkg_bytes(), ".gpkg")
        try:
            layer = ds.GetLayer(0)
            geom_type = layer.GetGeomType()
            self.assertNotEqual(
                geom_type,
                ogr.wkbGeometryCollection,
                "Global GeoPackage layer must not be declared as GEOMETRYCOLLECTION",
            )
        finally:
            ds = None
            os.unlink(path)

    def test_global_gpkg_has_point_and_polygon_features(self):
        import os

        ds, path = _open_bytes_as_ogr(self._get_gpkg_bytes(), ".gpkg")
        try:
            layer = ds.GetLayer(0)
            point_types = {ogr.wkbPoint, ogr.wkbPoint25D}
            polygon_types = {ogr.wkbPolygon, ogr.wkbPolygon25D, ogr.wkbMultiPolygon}
            found_point = False
            found_polygon = False
            for feat in layer:
                geom = feat.GetGeometryRef()
                if geom is None:
                    continue
                if geom.GetGeometryType() in point_types:
                    found_point = True
                elif geom.GetGeometryType() in polygon_types:
                    found_polygon = True
            self.assertTrue(found_point, "No Point features found in global GeoPackage")
            self.assertTrue(found_polygon, "No Polygon features found in global GeoPackage")
        finally:
            ds = None
            os.unlink(path)
