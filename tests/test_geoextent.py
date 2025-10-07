"""
Integration tests for Geoextent API endpoints.

Tests compare API responses against reference results from geoextent library.
Reference values are pre-computed and hardcoded for reliability and speed.
"""

import json
import os
from django.test import Client, TestCase
from django.core.files.uploadedfile import SimpleUploadedFile
from django.contrib.auth import get_user_model

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'optimap.settings')

User = get_user_model()


# Reference values generated from geoextent library
REFERENCE_VALUES = {
    'test_point': {
        'format': 'geojson',
        'geoextent_handler': 'handleVector',
        'bbox': [13.405, 52.52, 13.405, 52.52],
        'crs': '4326',
        'tbox': ['2023-01-15', '2023-01-15'],
        'file_size_bytes': 171
    },
    'test_polygon': {
        'format': 'geojson',
        'geoextent_handler': 'handleVector',
        'bbox': [9.5, 53.0, 10.5, 54.0],
        'crs': '4326',
        'tbox': ['2023-06-01', '2023-06-30'],
        'file_size_bytes': 305
    },
    'test_linestring': {
        'format': 'geojson',
        'geoextent_handler': 'handleVector',
        'bbox': [13.4, 52.5, 13.6, 52.7],
        'crs': '4326',
        'tbox': ['2023-12-25', '2023-12-25'],
        'file_size_bytes': 233
    },
    'directory_combined': {
        'format': 'folder',
        'crs': '4326',
        'bbox': [9.5, 52.5, 13.6, 54.0],
        'tbox': ['2023-01-15', '2023-12-25'],
        'file_size_bytes': 709
    }
}


class GeoextentExtractTest(TestCase):
    """Tests for /api/v1/geoextent/extract/ endpoint"""

    def setUp(self):
        self.client = Client()
        # Create test user and login
        self.user = User.objects.create_user('testuser', 'test@example.com', 'testpass')
        self.client.login(username='testuser', password='testpass')

        self.fixtures_dir = os.path.join(
            os.path.dirname(__file__), 'fixtures', 'geoextent'
        )

    def test_extract_point_structured_format(self):
        """Test extracting extent from point GeoJSON with structured format"""
        # Load test file
        with open(os.path.join(self.fixtures_dir, 'test_point.geojson'), 'rb') as f:
            file_content = f.read()

        # Reference values
        reference = REFERENCE_VALUES['test_point']

        # Call API
        response = self.client.post(
            '/api/v1/geoextent/extract/',
            {
                'file': SimpleUploadedFile('test_point.geojson', file_content),
                'bbox': 'true',
                'tbox': 'true',
                'response_format': 'structured'
            }
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()

        # Compare with reference
        self.assertTrue(data['success'])
        self.assertEqual(data['spatial_extent'], reference['bbox'])
        self.assertEqual(data['temporal_extent'], reference['tbox'])
        self.assertEqual(data['metadata']['crs'], reference['crs'])
        self.assertEqual(data['metadata']['file_format'], reference['format'])

    def test_extract_polygon_raw_format(self):
        """Test extracting extent from polygon GeoJSON with raw format"""
        with open(os.path.join(self.fixtures_dir, 'test_polygon.geojson'), 'rb') as f:
            file_content = f.read()

        # Reference values
        reference = REFERENCE_VALUES['test_polygon']

        # Call API with raw format
        response = self.client.post(
            '/api/v1/geoextent/extract/',
            {
                'file': SimpleUploadedFile('test_polygon.geojson', file_content),
                'bbox': 'true',
                'tbox': 'true',
                'response_format': 'raw'
            }
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()

        # Raw format should match geoextent output exactly
        self.assertEqual(data['format'], reference['format'])
        self.assertEqual(data['bbox'], reference['bbox'])
        self.assertEqual(data['tbox'], reference['tbox'])
        self.assertEqual(data['crs'], reference['crs'])

    def test_extract_geojson_response_format(self):
        """Test extracting extent with GeoJSON response format"""
        with open(os.path.join(self.fixtures_dir, 'test_linestring.geojson'), 'rb') as f:
            file_content = f.read()

        # Reference values
        reference = REFERENCE_VALUES['test_linestring']

        # Call API with geojson format
        response = self.client.post(
            '/api/v1/geoextent/extract/',
            {
                'file': SimpleUploadedFile('test_linestring.geojson', file_content),
                'bbox': 'true',
                'tbox': 'true',
                'response_format': 'geojson'
            }
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()

        # Check GeoJSON structure
        self.assertEqual(data['type'], 'Feature')
        self.assertIn('geometry', data)
        self.assertEqual(data['geometry']['type'], 'Polygon')

        # Verify temporal extent in properties
        self.assertEqual(
            data['properties']['temporal_extent'],
            reference['tbox']
        )

    def test_extract_wkt_response_format(self):
        """Test extracting extent with WKT response format"""
        with open(os.path.join(self.fixtures_dir, 'test_polygon.geojson'), 'rb') as f:
            file_content = f.read()

        response = self.client.post(
            '/api/v1/geoextent/extract/',
            {
                'file': SimpleUploadedFile('test_polygon.geojson', file_content),
                'bbox': 'true',
                'tbox': 'true',
                'response_format': 'wkt'
            }
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()

        # Check WKT structure
        self.assertIn('wkt', data)
        self.assertTrue(data['wkt'].startswith('POLYGON'))
        self.assertEqual(data['crs'], 'EPSG:4326')
        self.assertIn('temporal_extent', data)
        self.assertEqual(data['temporal_extent'], REFERENCE_VALUES['test_polygon']['tbox'])

    def test_extract_wkb_response_format(self):
        """Test extracting extent with WKB response format"""
        with open(os.path.join(self.fixtures_dir, 'test_point.geojson'), 'rb') as f:
            file_content = f.read()

        response = self.client.post(
            '/api/v1/geoextent/extract/',
            {
                'file': SimpleUploadedFile('test_point.geojson', file_content),
                'bbox': 'true',
                'tbox': 'true',
                'response_format': 'wkb'
            }
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()

        # Check WKB structure
        self.assertIn('wkb', data)
        self.assertIsInstance(data['wkb'], str)  # Hex string
        self.assertEqual(data['crs'], 'EPSG:4326')
        self.assertIn('temporal_extent', data)
        self.assertEqual(data['temporal_extent'], REFERENCE_VALUES['test_point']['tbox'])

    def test_extract_without_bbox(self):
        """Test extracting only temporal extent without bbox"""
        with open(os.path.join(self.fixtures_dir, 'test_point.geojson'), 'rb') as f:
            file_content = f.read()

        response = self.client.post(
            '/api/v1/geoextent/extract/',
            {
                'file': SimpleUploadedFile('test_point.geojson', file_content),
                'bbox': 'false',
                'tbox': 'true',
                'response_format': 'structured'
            }
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()

        self.assertTrue(data['success'])
        self.assertNotIn('spatial_extent', data)
        self.assertIn('temporal_extent', data)
        self.assertEqual(data['temporal_extent'], REFERENCE_VALUES['test_point']['tbox'])

    def test_extract_convex_hull(self):
        """Test extracting convex hull instead of bbox"""
        with open(os.path.join(self.fixtures_dir, 'test_polygon.geojson'), 'rb') as f:
            file_content = f.read()

        response = self.client.post(
            '/api/v1/geoextent/extract/',
            {
                'file': SimpleUploadedFile('test_polygon.geojson', file_content),
                'bbox': 'true',
                'convex_hull': 'true',
                'response_format': 'structured'
            }
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()

        # Convex hull returns points instead of bbox
        self.assertTrue(data['success'])
        self.assertIn('spatial_extent', data)
        # Convex hull format is different - list of coordinate pairs
        self.assertIsInstance(data['spatial_extent'], list)


class GeoextentBatchTest(TestCase):
    """Tests for /api/v1/geoextent/extract-batch/ endpoint"""

    def setUp(self):
        self.client = Client()
        # Create test user and login
        self.user = User.objects.create_user('testuser', 'test@example.com', 'testpass')
        self.client.login(username='testuser', password='testpass')

        self.fixtures_dir = os.path.join(
            os.path.dirname(__file__), 'fixtures', 'geoextent'
        )

    def test_batch_multiple_files_combined(self):
        """Test batch processing with extent combination"""
        # Load all test files
        files = []
        for filename in ['test_point.geojson', 'test_polygon.geojson', 'test_linestring.geojson']:
            with open(os.path.join(self.fixtures_dir, filename), 'rb') as f:
                files.append(SimpleUploadedFile(filename, f.read()))

        # Reference values for combined directory
        reference = REFERENCE_VALUES['directory_combined']

        # Call API
        response = self.client.post(
            '/api/v1/geoextent/extract-batch/',
            {
                'files': files,
                'bbox': 'true',
                'tbox': 'true',
                'response_format': 'structured'
            }
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()

        # Check response structure
        self.assertTrue(data['success'])
        self.assertEqual(data['files_processed'], 3)
        self.assertIn('combined_extent', data)
        self.assertIn('individual_results', data)

        # Compare combined extent with reference
        self.assertEqual(
            data['combined_extent']['spatial_extent'],
            reference['bbox']
        )
        self.assertEqual(
            data['combined_extent']['temporal_extent'],
            reference['tbox']
        )

        # Check individual results count
        self.assertEqual(len(data['individual_results']), 3)

    def test_batch_individual_results(self):
        """Test batch processing returns both combined and individual results"""
        files = []
        for filename in ['test_point.geojson', 'test_polygon.geojson']:
            with open(os.path.join(self.fixtures_dir, filename), 'rb') as f:
                files.append(SimpleUploadedFile(filename, f.read()))

        response = self.client.post(
            '/api/v1/geoextent/extract-batch/',
            {
                'files': files,
                'bbox': 'true',
                'tbox': 'true',
                'response_format': 'structured'
            }
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()

        # Should have both combined extent and individual results
        self.assertTrue(data['success'])
        self.assertIn('combined_extent', data)
        self.assertIn('individual_results', data)
        self.assertEqual(len(data['individual_results']), 2)

        # Verify individual results match reference values
        for result in data['individual_results']:
            if result['filename'] == 'test_point.geojson':
                self.assertEqual(result['spatial_extent'], REFERENCE_VALUES['test_point']['bbox'])
                self.assertEqual(result['temporal_extent'], REFERENCE_VALUES['test_point']['tbox'])
            elif result['filename'] == 'test_polygon.geojson':
                self.assertEqual(result['spatial_extent'], REFERENCE_VALUES['test_polygon']['bbox'])
                self.assertEqual(result['temporal_extent'], REFERENCE_VALUES['test_polygon']['tbox'])

    def test_batch_raw_format(self):
        """Test batch processing with raw response format"""
        with open(os.path.join(self.fixtures_dir, 'test_point.geojson'), 'rb') as f:
            file_content = f.read()

        response = self.client.post(
            '/api/v1/geoextent/extract-batch/',
            {
                'files': [SimpleUploadedFile('test_point.geojson', file_content)],
                'bbox': 'true',
                'tbox': 'true',
                'response_format': 'raw'
            }
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()

        # Check that individual results are in raw format
        self.assertEqual(len(data['individual_results']), 1)
        result = data['individual_results'][0]

        # Raw format should have geoextent fields
        self.assertIn('format', result)
        self.assertEqual(result['format'], 'geojson')
        self.assertEqual(result['bbox'], REFERENCE_VALUES['test_point']['bbox'])

    def test_batch_geojson_format(self):
        """Test batch processing with GeoJSON response format"""
        with open(os.path.join(self.fixtures_dir, 'test_polygon.geojson'), 'rb') as f:
            file_content = f.read()

        response = self.client.post(
            '/api/v1/geoextent/extract-batch/',
            {
                'files': [SimpleUploadedFile('test_polygon.geojson', file_content)],
                'bbox': 'true',
                'response_format': 'geojson'
            }
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()

        # Combined extent should be GeoJSON Feature
        combined = data['combined_extent']
        self.assertEqual(combined['type'], 'Feature')
        self.assertIn('geometry', combined)

        # Individual results should also be GeoJSON
        self.assertEqual(data['individual_results'][0]['type'], 'Feature')


class GeoextentRemoteTest(TestCase):
    """Tests for /api/v1/geoextent/extract-remote/ endpoint

    Note: These tests make actual network calls and may fail if:
    - No internet connection
    - Repository is unavailable
    - DOI resolver is down
    """

    # Reference value from Zenodo dataset 10.5281/zenodo.4593540
    # NOTE: geoextent.fromRemote() has a bug where it returns coordinates in
    # [minLat, minLon, maxLat, maxLon] format instead of the GeoJSON standard
    # [minLon, minLat, maxLon, maxLat]. This needs to be fixed upstream in geoextent.
    # Pennsylvania coordinates: ~40°N latitude, ~75-80°W longitude
    ZENODO_REFERENCE = {
        'identifier': '10.5281/zenodo.4593540',
        'bbox': [39.642802545572735, -80.71456319678893, 42.256308231814586, -74.78657735361809],
        'tbox': ['2006-02-02', '2018-08-27'],
        'crs': '4326'
    }

    def setUp(self):
        self.client = Client()
        # Create test user and login
        self.user = User.objects.create_user('testuser', 'test@example.com', 'testpass')
        self.client.login(username='testuser', password='testpass')

    def test_remote_single_identifier(self):
        """Test extracting from single remote identifier"""
        identifier = self.ZENODO_REFERENCE['identifier']

        # Call API
        response = self.client.post(
            '/api/v1/geoextent/extract-remote/',
            json.dumps({
                'identifiers': [identifier],
                'bbox': True,
                'tbox': True,
                'response_format': 'structured'
            }),
            content_type='application/json'
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()

        # For single identifier, should return simple response
        self.assertIn('spatial_extent', data)
        self.assertEqual(data['spatial_extent'], self.ZENODO_REFERENCE['bbox'])
        self.assertEqual(data['temporal_extent'], self.ZENODO_REFERENCE['tbox'])

    def test_remote_multiple_identifiers(self):
        """Test extracting from multiple remote identifiers"""
        identifiers = [
            '10.5281/zenodo.4593540',
            '10.5281/zenodo.7416089'  # This might fail (404), but should be handled
        ]

        # Call API
        response = self.client.post(
            '/api/v1/geoextent/extract-remote/',
            json.dumps({
                'identifiers': identifiers,
                'bbox': True,
                'tbox': True,
                'response_format': 'structured'
            }),
            content_type='application/json'
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()

        # Should have combined extent and individual results
        self.assertIn('combined_extent', data)
        self.assertIn('individual_results', data)
        self.assertIn('extraction_metadata', data)

        # Should process 2 identifiers
        self.assertEqual(data['extraction_metadata']['total_resources'], 2)

    def test_remote_raw_format(self):
        """Test remote extraction with raw format"""
        identifier = self.ZENODO_REFERENCE['identifier']

        response = self.client.post(
            '/api/v1/geoextent/extract-remote/',
            json.dumps({
                'identifiers': [identifier],
                'bbox': True,
                'tbox': True,
                'response_format': 'raw'
            }),
            content_type='application/json'
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()

        # Raw format should have geoextent fields
        self.assertIn('format', data)
        self.assertEqual(data['format'], 'remote')

    def test_remote_single_identifier_simple_response(self):
        """Test single identifier returns simplified response"""
        identifier = self.ZENODO_REFERENCE['identifier']

        response = self.client.post(
            '/api/v1/geoextent/extract-remote/',
            json.dumps({
                'identifiers': [identifier],
                'bbox': True
            }),
            content_type='application/json'
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()

        # Single identifier returns simple format (no combined_extent wrapper)
        self.assertIn('spatial_extent', data)
        self.assertNotIn('combined_extent', data)


class GeoextentRemoteGetTest(TestCase):
    """Tests for /api/v1/geoextent/extract-remote/ GET endpoint"""

    # Reference value from Zenodo dataset 10.5281/zenodo.4593540
    # NOTE: geoextent.fromRemote() has a bug where it returns coordinates in
    # [minLat, minLon, maxLat, maxLon] format instead of the GeoJSON standard
    # [minLon, minLat, maxLon, maxLat]. This needs to be fixed upstream in geoextent.
    # Pennsylvania coordinates: ~40°N latitude, ~75-80°W longitude
    ZENODO_REFERENCE = {
        'identifier': '10.5281/zenodo.4593540',
        'bbox': [39.642802545572735, -80.71456319678893, 42.256308231814586, -74.78657735361809],
        'tbox': ['2006-02-02', '2018-08-27'],
        'crs': '4326'
    }

    def setUp(self):
        self.client = Client()
        # Create test user and login
        self.user = User.objects.create_user('testuser', 'test@example.com', 'testpass')
        self.client.login(username='testuser', password='testpass')

    def test_get_single_identifier(self):
        """Test GET request with single identifier"""
        identifier = self.ZENODO_REFERENCE['identifier']

        response = self.client.get(
            '/api/v1/geoextent/extract-remote/',
            {
                'identifiers': identifier,
                'bbox': 'true',
                'tbox': 'true',
                'response_format': 'structured'
            }
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()

        # Single identifier returns simple format
        self.assertIn('spatial_extent', data)
        self.assertEqual(data['spatial_extent'], self.ZENODO_REFERENCE['bbox'])
        self.assertEqual(data['temporal_extent'], self.ZENODO_REFERENCE['tbox'])

    def test_get_multiple_identifiers(self):
        """Test GET request with comma-separated identifiers"""
        identifiers = '10.5281/zenodo.4593540,10.5281/zenodo.7416089'

        response = self.client.get(
            '/api/v1/geoextent/extract-remote/',
            {
                'identifiers': identifiers,
                'bbox': 'true',
                'tbox': 'true',
                'response_format': 'structured'
            }
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()

        # Multiple identifiers return combined_extent
        self.assertIn('combined_extent', data)
        self.assertIn('individual_results', data)
        self.assertIn('extraction_metadata', data)

    def test_get_geojson_format(self):
        """Test GET request with GeoJSON response format"""
        identifier = self.ZENODO_REFERENCE['identifier']

        response = self.client.get(
            '/api/v1/geoextent/extract-remote/',
            {
                'identifiers': identifier,
                'bbox': 'true',
                'response_format': 'geojson'
            }
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()

        # GeoJSON format should have Feature structure
        self.assertEqual(data['type'], 'Feature')
        self.assertIn('geometry', data)
        self.assertIn('properties', data)

    def test_get_wkt_format(self):
        """Test GET request with WKT response format"""
        identifier = self.ZENODO_REFERENCE['identifier']

        response = self.client.get(
            '/api/v1/geoextent/extract-remote/',
            {
                'identifiers': identifier,
                'bbox': 'true',
                'response_format': 'wkt'
            }
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()

        # WKT format returns string
        self.assertIn('wkt', data)
        self.assertIn('crs', data)
        self.assertIsInstance(data['wkt'], str)
        self.assertTrue(data['wkt'].startswith('POLYGON'))

    def test_get_missing_identifiers(self):
        """Test GET request without identifiers parameter"""
        response = self.client.get(
            '/api/v1/geoextent/extract-remote/',
            {'bbox': 'true'}
        )

        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertIn('identifiers', data)


class GeoextentErrorHandlingTest(TestCase):
    """Tests for error handling in geoextent endpoints"""

    def setUp(self):
        self.client = Client()
        # Create test user and login
        self.user = User.objects.create_user('testuser', 'test@example.com', 'testpass')
        self.client.login(username='testuser', password='testpass')

    def test_extract_no_file(self):
        """Test extract endpoint with no file provided"""
        response = self.client.post(
            '/api/v1/geoextent/extract/',
            {'bbox': 'true'}
        )

        self.assertEqual(response.status_code, 400)

    def test_batch_no_files(self):
        """Test batch endpoint with no files provided"""
        response = self.client.post(
            '/api/v1/geoextent/extract-batch/',
            {'bbox': 'true'}
        )

        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertFalse(data['success'])
        self.assertIn('error', data)

    def test_remote_empty_identifiers(self):
        """Test remote endpoint with empty identifiers list"""
        response = self.client.post(
            '/api/v1/geoextent/extract-remote/',
            json.dumps({
                'identifiers': [],
                'bbox': True
            }),
            content_type='application/json'
        )

        self.assertEqual(response.status_code, 400)

    def test_extract_invalid_format(self):
        """Test extract with invalid response format"""
        fixtures_dir = os.path.join(
            os.path.dirname(__file__), 'fixtures', 'geoextent'
        )
        with open(os.path.join(fixtures_dir, 'test_point.geojson'), 'rb') as f:
            file_content = f.read()

        response = self.client.post(
            '/api/v1/geoextent/extract/',
            {
                'file': SimpleUploadedFile('test_point.geojson', file_content),
                'bbox': 'true',
                'response_format': 'invalid_format'
            }
        )

        self.assertEqual(response.status_code, 400)
