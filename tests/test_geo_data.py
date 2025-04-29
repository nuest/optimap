import os
import json
import tempfile
from datetime import datetime, timedelta
from django.test import TestCase
from django.core.serializers import serialize
import fiona
import gzip
from django.urls import reverse
import re
from publications.models import Publication
from publications.views import generate_geopackage
from publications.tasks import regenerate_geojson_cache

class GeoDataAlternativeTestCase(TestCase):
    def setUp(self):
        Publication.objects.all().delete()
        wkt_point1 = "GEOMETRYCOLLECTION(POINT(7.59573 51.96944))"
        wkt_point2 = "GEOMETRYCOLLECTION(POINT(8.59573 52.96944))"
        wkt_point3 = "GEOMETRYCOLLECTION(POINT(9.59573 53.96944))"
        
        Publication.objects.create(
            title="Publication One",
            abstract="Abstract of publication one.",
            publicationDate="2020-01-01",
            url="http://example.com/1",
            source="Source One",
            doi="10.0001/one",
            geometry=wkt_point1,
            timeperiod_startdate=["2020-01-01"],
            timeperiod_enddate=["2020-12-31"],
        )
        Publication.objects.create(
            title="Publication Two",
            abstract="Abstract of publication two.",
            publicationDate="2020-06-01",
            url="http://example.com/2",
            source="Source Two",
            doi="10.0001/two",
            geometry=wkt_point2,
            timeperiod_startdate=["2020-06-01"],
            timeperiod_enddate=["2020-12-31"],
        )
        Publication.objects.create(
            title="Publication Three",
            abstract="Abstract of publication three.",
            publicationDate="2020-09-01",
            url="http://example.com/3",
            source="Source Three",
            doi="10.0001/three",
            geometry=wkt_point3,
            timeperiod_startdate=["2020-09-01"],
            timeperiod_enddate=["2020-12-31"],
        )
    
    def test_geojson_generation(self):
        geojson_data = serialize('geojson', Publication.objects.all(), geometry_field='geometry')
        self.assertTrue(len(geojson_data) > 0, "GeoJSON data should not be empty")
        geojson_obj = json.loads(geojson_data)
        self.assertEqual(geojson_obj.get("type"), "FeatureCollection", "GeoJSON type should be FeatureCollection")
        features = geojson_obj.get("features", [])
        self.assertEqual(len(features), Publication.objects.count(), "Feature count should match Publication count")
        self.assertIn("title", features[0]["properties"], "Each feature should have a 'title' property")

    def test_geopackage_generation(self):
        gpkg_path = generate_geopackage()
        self.assertTrue(os.path.exists(gpkg_path), "GeoPackage file should exist")
        with fiona.open(gpkg_path, layer='publications') as layer:
            features = list(layer)
            self.assertEqual(len(features), Publication.objects.count(),
                             "Feature count in GeoPackage should match the Publication count")

    def test_update_reflects_in_generated_data(self):
        initial_geojson = serialize('geojson', Publication.objects.all(), geometry_field='geometry')
        initial_obj = json.loads(initial_geojson)
        initial_title = initial_obj['features'][0]['properties']['title']
        pub = Publication.objects.first()
        pub.title += " Updated"
        pub.save()
        
        updated_geojson = serialize('geojson', Publication.objects.all(), geometry_field='geometry')
        updated_obj = json.loads(updated_geojson)
        updated_title = updated_obj['features'][0]['properties']['title']
        self.assertNotEqual(initial_title, updated_title,
                            "The title of the first publication should update in the GeoJSON output")

        # Test GeoPackage update
        initial_gpkg = open(generate_geopackage(), 'rb').read()
        updated_gpkg = open(generate_geopackage(), 'rb').read()
        self.assertNotEqual(initial_gpkg, updated_gpkg,
                            "The GeoPackage data should update when a Publication changes")

    def test_data_endpoint(self):
        response = self.client.get(reverse('optimap:data_and_api'))
        self.assertEqual(response.status_code, 200, "Data endpoint should return status 200")
        content = response.content.decode()
        self.assertIn("Data dumps are recreated every 6 hours.", content,
                      "The data page should mention the six-hour schedule")
        match = re.search(r'Last updated:\s*(\S+)', content)
        self.assertIsNotNone(match, "Data page should display a Last updated timestamp")
        self.assertTrue(match.group(1).strip() != "", "Last updated timestamp should not be empty")

    def test_download_geojson_gzip(self):
        # Ensure cache exists
        regenerate_geojson_cache()
        url = reverse('optimap:download_geojson')
        response = self.client.get(url, HTTP_ACCEPT_ENCODING='gzip')
        self.assertEqual(response.status_code, 200, "Gzip download should return status 200")
        self.assertEqual(response['Content-Encoding'], 'gzip', "Response should be gzipped when requested")
        self.assertEqual(response['Content-Type'], 'application/json', "Content-Type should be application/json")
        self.assertIn('publications.geojson', response['Content-Disposition'],
                      "Content-Disposition should include the filename")

    def test_download_geojson_no_gzip(self):
        # Ensure cache exists
        regenerate_geojson_cache()
        url = reverse('optimap:download_geojson')
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200, "JSON download should return status 200")
        self.assertNotIn('Content-Encoding', response, "Response should not be gzipped when not requested")
        self.assertEqual(response['Content-Type'], 'application/json', "Content-Type should be application/json")
        self.assertIn('publications.geojson', response['Content-Disposition'],
                      "Content-Disposition should include the filename")

    # New tests for caching functionality
    def test_regenerate_geojson_cache_creates_files(self):
        # Remove any existing cache
        cache_dir = tempfile.gettempdir() + '/optimap_cache'
        json_path = os.path.join(cache_dir, 'geojson_cache.json')
        gzip_path = os.path.join(cache_dir, 'geojson_cache.json.gz')
        if os.path.exists(json_path): os.remove(json_path)
        if os.path.exists(gzip_path): os.remove(gzip_path)

        returned_path = regenerate_geojson_cache()
        # The function should return the JSON path
        self.assertEqual(returned_path, json_path)
        # Both JSON and gz files should now exist
        self.assertTrue(os.path.exists(json_path), "GeoJSON cache file should be created")
        self.assertTrue(os.path.exists(gzip_path), "Gzipped GeoJSON cache file should be created")

    def test_cached_json_content_valid(self):
        # Generate cache
        json_path = regenerate_geojson_cache()
        with open(json_path, 'r') as f:
            obj = json.load(f)
        # It should have type and features keys
        self.assertEqual(obj.get('type'), 'FeatureCollection')
        self.assertIn('features', obj)
        # Feature count should match database
        self.assertEqual(len(obj['features']), Publication.objects.filter(status='p').count())

    def test_cached_gzip_can_be_unpacked(self):
        # Generate cache
        regenerate_geojson_cache()
        gzip_path = os.path.join(tempfile.gettempdir(), 'optimap_cache', 'geojson_cache.json.gz')
        with gzip.open(gzip_path, 'rt') as f:
            obj = json.load(f)
        self.assertEqual(obj.get('type'), 'FeatureCollection')
        self.assertIn('features', obj)
        self.assertEqual(len(obj['features']), Publication.objects.filter(status='p').count())
