"""
Unit tests for Work.get_center_coordinate() method.

Tests center coordinate calculation for different geometry types:
- Point
- LineString
- Polygon
- GeometryCollection
"""

from django.test import TestCase
from django.contrib.gis.geos import Point, LineString, Polygon, GeometryCollection
from works.models import Work


class CenterCoordinateTest(TestCase):
    """Test center coordinate calculation for different geometry types."""

    def setUp(self):
        """Create a base publication for testing."""
        self.work = Work.objects.create(
            title="Test Publication",
            doi="10.1234/test",
            status="p"
        )

    def test_center_coordinate_point(self):
        """Test center coordinate calculation for a single Point geometry."""
        # Create a publication with a single point
        self.work.geometry = GeometryCollection(Point(10.0, 20.0))
        self.work.save()

        # Get center coordinate
        center = self.work.get_center_coordinate()

        # For a single point, the center should be the point itself
        self.assertIsNotNone(center)
        lon, lat = center
        self.assertAlmostEqual(lon, 10.0, places=5)
        self.assertAlmostEqual(lat, 20.0, places=5)

    def test_center_coordinate_linestring(self):
        """Test center coordinate calculation for a LineString geometry."""
        # Create a publication with a line from (0, 0) to (10, 10)
        line = LineString([(0.0, 0.0), (10.0, 10.0)])
        self.work.geometry = GeometryCollection(line)
        self.work.save()

        # Get center coordinate
        center = self.work.get_center_coordinate()

        # The bounding box center of a line from (0,0) to (10,10) should be (5, 5)
        self.assertIsNotNone(center)
        lon, lat = center
        self.assertAlmostEqual(lon, 5.0, places=5)
        self.assertAlmostEqual(lat, 5.0, places=5)

    def test_center_coordinate_polygon(self):
        """Test center coordinate calculation for a Polygon geometry."""
        # Create a publication with a rectangular polygon
        # Rectangle from (0, 0) to (10, 20)
        polygon = Polygon([(0.0, 0.0), (10.0, 0.0), (10.0, 20.0), (0.0, 20.0), (0.0, 0.0)])
        self.work.geometry = GeometryCollection(polygon)
        self.work.save()

        # Get center coordinate
        center = self.work.get_center_coordinate()

        # The bounding box center should be (5, 10)
        self.assertIsNotNone(center)
        lon, lat = center
        self.assertAlmostEqual(lon, 5.0, places=5)
        self.assertAlmostEqual(lat, 10.0, places=5)

    def test_center_coordinate_multiple_geometries(self):
        """Test center coordinate calculation for a GeometryCollection with multiple geometries."""
        # Create a publication with multiple points
        point1 = Point(0.0, 0.0)
        point2 = Point(10.0, 10.0)
        self.work.geometry = GeometryCollection(point1, point2)
        self.work.save()

        # Get center coordinate
        center = self.work.get_center_coordinate()

        # The bounding box center of points at (0,0) and (10,10) should be (5, 5)
        self.assertIsNotNone(center)
        lon, lat = center
        self.assertAlmostEqual(lon, 5.0, places=5)
        self.assertAlmostEqual(lat, 5.0, places=5)

    def test_center_coordinate_no_geometry(self):
        """Test center coordinate calculation when publication has no geometry."""
        # Don't set any geometry
        self.work.geometry = None
        self.work.save()

        # Get center coordinate
        center = self.work.get_center_coordinate()

        # Should return None when no geometry
        self.assertIsNone(center)

    def test_center_coordinate_complex_polygon(self):
        """Test center coordinate calculation for a complex polygon (not centered at origin)."""
        # Create a polygon from (100, 50) to (120, 70)
        polygon = Polygon([
            (100.0, 50.0),
            (120.0, 50.0),
            (120.0, 70.0),
            (100.0, 70.0),
            (100.0, 50.0)
        ])
        self.work.geometry = GeometryCollection(polygon)
        self.work.save()

        # Get center coordinate
        center = self.work.get_center_coordinate()

        # The bounding box center should be (110, 60)
        self.assertIsNotNone(center)
        lon, lat = center
        self.assertAlmostEqual(lon, 110.0, places=5)
        self.assertAlmostEqual(lat, 60.0, places=5)


class ExtremePointsTest(TestCase):
    """Test extreme points calculation for different geometry types."""

    def setUp(self):
        """Create a base publication for testing."""
        self.work = Work.objects.create(
            title="Test Publication",
            doi="10.1234/test-extremes",
            status="p"
        )

    def test_extreme_points_single_point(self):
        """Test extreme points for a single point - all should be the same."""
        point = Point(10.0, 20.0)
        self.work.geometry = GeometryCollection(point)
        self.work.save()

        extremes = self.work.get_extreme_points()

        self.assertIsNotNone(extremes)
        # All extreme points should be the same for a single point
        self.assertAlmostEqual(extremes['north'][0], 10.0, places=5)
        self.assertAlmostEqual(extremes['north'][1], 20.0, places=5)
        self.assertAlmostEqual(extremes['south'][0], 10.0, places=5)
        self.assertAlmostEqual(extremes['south'][1], 20.0, places=5)
        self.assertAlmostEqual(extremes['east'][0], 10.0, places=5)
        self.assertAlmostEqual(extremes['east'][1], 20.0, places=5)
        self.assertAlmostEqual(extremes['west'][0], 10.0, places=5)
        self.assertAlmostEqual(extremes['west'][1], 20.0, places=5)

    def test_extreme_points_linestring(self):
        """Test extreme points for a diagonal line."""
        line = LineString([(0.0, 0.0), (10.0, 10.0)])
        self.work.geometry = GeometryCollection(line)
        self.work.save()

        extremes = self.work.get_extreme_points()

        self.assertIsNotNone(extremes)
        # Northernmost point (highest Y)
        self.assertAlmostEqual(extremes['north'][0], 10.0, places=5)
        self.assertAlmostEqual(extremes['north'][1], 10.0, places=5)
        # Southernmost point (lowest Y)
        self.assertAlmostEqual(extremes['south'][0], 0.0, places=5)
        self.assertAlmostEqual(extremes['south'][1], 0.0, places=5)
        # Easternmost point (highest X)
        self.assertAlmostEqual(extremes['east'][0], 10.0, places=5)
        self.assertAlmostEqual(extremes['east'][1], 10.0, places=5)
        # Westernmost point (lowest X)
        self.assertAlmostEqual(extremes['west'][0], 0.0, places=5)
        self.assertAlmostEqual(extremes['west'][1], 0.0, places=5)

    def test_extreme_points_rectangle(self):
        """Test extreme points for a rectangular polygon."""
        # Rectangle from (0, 0) to (10, 20)
        polygon = Polygon([(0.0, 0.0), (10.0, 0.0), (10.0, 20.0), (0.0, 20.0), (0.0, 0.0)])
        self.work.geometry = GeometryCollection(polygon)
        self.work.save()

        extremes = self.work.get_extreme_points()

        self.assertIsNotNone(extremes)
        # Northernmost point (highest Y = 20)
        self.assertAlmostEqual(extremes['north'][1], 20.0, places=5)
        # X can be either 0 or 10 (both vertices have Y=20)
        self.assertIn(extremes['north'][0], [0.0, 10.0])

        # Southernmost point (lowest Y = 0)
        self.assertAlmostEqual(extremes['south'][1], 0.0, places=5)
        # X can be either 0 or 10 (both vertices have Y=0)
        self.assertIn(extremes['south'][0], [0.0, 10.0])

        # Easternmost point (highest X = 10)
        self.assertAlmostEqual(extremes['east'][0], 10.0, places=5)
        # Y can be either 0 or 20 (both vertices have X=10)
        self.assertIn(extremes['east'][1], [0.0, 20.0])

        # Westernmost point (lowest X = 0)
        self.assertAlmostEqual(extremes['west'][0], 0.0, places=5)
        # Y can be either 0 or 20 (both vertices have X=0)
        self.assertIn(extremes['west'][1], [0.0, 20.0])

    def test_extreme_points_complex_polygon(self):
        """Test extreme points for a more complex polygon."""
        # Create an L-shaped polygon
        polygon = Polygon([
            (0.0, 0.0),
            (10.0, 0.0),
            (10.0, 5.0),
            (5.0, 5.0),
            (5.0, 10.0),
            (0.0, 10.0),
            (0.0, 0.0)
        ])
        self.work.geometry = GeometryCollection(polygon)
        self.work.save()

        extremes = self.work.get_extreme_points()

        self.assertIsNotNone(extremes)
        # Northernmost point (highest Y = 10)
        self.assertAlmostEqual(extremes['north'][1], 10.0, places=5)
        # Southernmost point (lowest Y = 0)
        self.assertAlmostEqual(extremes['south'][1], 0.0, places=5)
        # Easternmost point (highest X = 10)
        self.assertAlmostEqual(extremes['east'][0], 10.0, places=5)
        # Westernmost point (lowest X = 0)
        self.assertAlmostEqual(extremes['west'][0], 0.0, places=5)

    def test_extreme_points_no_geometry(self):
        """Test extreme points when publication has no geometry."""
        self.work.geometry = None
        self.work.save()

        extremes = self.work.get_extreme_points()

        self.assertIsNone(extremes)


class ComplexGeometryTest(TestCase):
    """Test center coordinate and extreme points for complex and mixed geometry types."""

    def setUp(self):
        """Create a base publication for testing."""
        self.work = Work.objects.create(
            title="Test Publication - Complex Geometries",
            doi="10.1234/test-complex",
            status="p"
        )

    def test_triangle_geometry(self):
        """Test with a triangular polygon."""
        # Equilateral-ish triangle
        triangle = Polygon([(0.0, 0.0), (10.0, 0.0), (5.0, 8.66), (0.0, 0.0)])
        self.work.geometry = GeometryCollection(triangle)
        self.work.save()

        center = self.work.get_center_coordinate()
        extremes = self.work.get_extreme_points()

        # Center should be roughly in the middle
        self.assertIsNotNone(center)
        lon, lat = center
        self.assertAlmostEqual(lon, 5.0, places=1)
        self.assertAlmostEqual(lat, 4.33, places=1)

        # Extremes
        self.assertIsNotNone(extremes)
        self.assertAlmostEqual(extremes['south'][1], 0.0, places=5)
        self.assertAlmostEqual(extremes['north'][1], 8.66, places=2)
        self.assertAlmostEqual(extremes['west'][0], 0.0, places=5)
        self.assertAlmostEqual(extremes['east'][0], 10.0, places=5)

    def test_pentagon_geometry(self):
        """Test with a pentagon polygon."""
        # Regular pentagon (approximately)
        import math
        cx, cy, r = 50.0, 50.0, 10.0
        points = []
        for i in range(5):
            angle = 2 * math.pi * i / 5 - math.pi / 2
            x = cx + r * math.cos(angle)
            y = cy + r * math.sin(angle)
            points.append((x, y))
        points.append(points[0])  # Close the polygon

        pentagon = Polygon(points)
        self.work.geometry = GeometryCollection(pentagon)
        self.work.save()

        center = self.work.get_center_coordinate()
        extremes = self.work.get_extreme_points()

        # Center should be near the pentagon center (bbox center may not match geometric center)
        self.assertIsNotNone(center)
        lon, lat = center
        # Bounding box center might be slightly off from geometric center
        self.assertAlmostEqual(lon, cx, delta=2.0)
        self.assertAlmostEqual(lat, cy, delta=2.0)

        # Extremes should be within radius of center
        self.assertIsNotNone(extremes)
        self.assertGreater(extremes['north'][1], cy - r)
        self.assertLess(extremes['south'][1], cy + r)
        self.assertGreater(extremes['east'][0], cx - r)
        self.assertLess(extremes['west'][0], cx + r)

    def test_concave_polygon(self):
        """Test with a concave (non-convex) polygon."""
        # Star-like concave polygon
        concave = Polygon([
            (0.0, 5.0),
            (2.0, 2.0),
            (5.0, 0.0),
            (3.0, 3.0),
            (5.0, 5.0),
            (2.5, 4.0),
            (0.0, 5.0)
        ])
        self.work.geometry = GeometryCollection(concave)
        self.work.save()

        center = self.work.get_center_coordinate()
        extremes = self.work.get_extreme_points()

        # Should handle concave polygons correctly
        self.assertIsNotNone(center)
        self.assertIsNotNone(extremes)

        # Verify extreme points match the vertices
        self.assertAlmostEqual(extremes['north'][1], 5.0, places=5)
        self.assertAlmostEqual(extremes['south'][1], 0.0, places=5)
        self.assertAlmostEqual(extremes['east'][0], 5.0, places=5)
        self.assertAlmostEqual(extremes['west'][0], 0.0, places=5)

    def test_polygon_with_hole(self):
        """Test with a polygon that has an interior hole."""
        from django.contrib.gis.geos import LinearRing

        # Outer ring
        outer_ring = LinearRing((0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0), (0.0, 0.0))
        # Inner ring (hole)
        inner_ring = LinearRing((3.0, 3.0), (7.0, 3.0), (7.0, 7.0), (3.0, 7.0), (3.0, 3.0))

        polygon_with_hole = Polygon(outer_ring, [inner_ring])
        self.work.geometry = GeometryCollection(polygon_with_hole)
        self.work.save()

        center = self.work.get_center_coordinate()
        extremes = self.work.get_extreme_points()

        # Center should be at center of bounding box (hole doesn't affect bbox)
        self.assertIsNotNone(center)
        lon, lat = center
        self.assertAlmostEqual(lon, 5.0, places=5)
        self.assertAlmostEqual(lat, 5.0, places=5)

        # Extremes should be from outer ring only
        self.assertIsNotNone(extremes)
        self.assertAlmostEqual(extremes['north'][1], 10.0, places=5)
        self.assertAlmostEqual(extremes['south'][1], 0.0, places=5)
        self.assertAlmostEqual(extremes['east'][0], 10.0, places=5)
        self.assertAlmostEqual(extremes['west'][0], 0.0, places=5)

    def test_mixed_point_and_line(self):
        """Test with a GeometryCollection containing both points and lines."""
        point = Point(0.0, 0.0)
        line = LineString([(10.0, 10.0), (20.0, 20.0)])

        self.work.geometry = GeometryCollection(point, line)
        self.work.save()

        center = self.work.get_center_coordinate()
        extremes = self.work.get_extreme_points()

        # Center should be middle of bounding box from (0,0) to (20,20)
        self.assertIsNotNone(center)
        lon, lat = center
        self.assertAlmostEqual(lon, 10.0, places=5)
        self.assertAlmostEqual(lat, 10.0, places=5)

        # Extremes
        self.assertIsNotNone(extremes)
        self.assertAlmostEqual(extremes['south'][0], 0.0, places=5)
        self.assertAlmostEqual(extremes['south'][1], 0.0, places=5)
        self.assertAlmostEqual(extremes['north'][0], 20.0, places=5)
        self.assertAlmostEqual(extremes['north'][1], 20.0, places=5)

    def test_mixed_point_line_polygon(self):
        """Test with a GeometryCollection containing point, line, and polygon."""
        point = Point(0.0, 0.0)
        line = LineString([(5.0, 5.0), (15.0, 5.0)])
        polygon = Polygon([(20.0, 0.0), (30.0, 0.0), (30.0, 10.0), (20.0, 10.0), (20.0, 0.0)])

        self.work.geometry = GeometryCollection(point, line, polygon)
        self.work.save()

        center = self.work.get_center_coordinate()
        extremes = self.work.get_extreme_points()

        # Center should be middle of overall bounding box from (0,0) to (30,10)
        self.assertIsNotNone(center)
        lon, lat = center
        self.assertAlmostEqual(lon, 15.0, places=5)
        self.assertAlmostEqual(lat, 5.0, places=5)

        # Extremes should span all geometries
        self.assertIsNotNone(extremes)
        self.assertAlmostEqual(extremes['west'][0], 0.0, places=5)
        self.assertAlmostEqual(extremes['east'][0], 30.0, places=5)
        self.assertAlmostEqual(extremes['south'][1], 0.0, places=5)
        self.assertAlmostEqual(extremes['north'][1], 10.0, places=5)

    def test_multipoint_geometry(self):
        """Test with multiple scattered points."""
        points = [
            Point(0.0, 0.0),
            Point(100.0, 50.0),
            Point(50.0, 100.0),
            Point(-50.0, 25.0)
        ]
        self.work.geometry = GeometryCollection(*points)
        self.work.save()

        center = self.work.get_center_coordinate()
        extremes = self.work.get_extreme_points()

        # Center should be in the middle of bounding box
        self.assertIsNotNone(center)
        lon, lat = center
        # Bounding box: x from -50 to 100 (center 25), y from 0 to 100 (center 50)
        self.assertAlmostEqual(lon, 25.0, places=5)
        self.assertAlmostEqual(lat, 50.0, places=5)

        # Extremes
        self.assertIsNotNone(extremes)
        self.assertAlmostEqual(extremes['west'][0], -50.0, places=5)
        self.assertAlmostEqual(extremes['east'][0], 100.0, places=5)
        self.assertAlmostEqual(extremes['south'][1], 0.0, places=5)
        self.assertAlmostEqual(extremes['north'][1], 100.0, places=5)

    def test_multilinestring_geometry(self):
        """Test with multiple line segments."""
        line1 = LineString([(0.0, 0.0), (10.0, 0.0)])
        line2 = LineString([(0.0, 10.0), (10.0, 10.0)])
        line3 = LineString([(5.0, 0.0), (5.0, 10.0)])

        self.work.geometry = GeometryCollection(line1, line2, line3)
        self.work.save()

        center = self.work.get_center_coordinate()
        extremes = self.work.get_extreme_points()

        # Bounding box from (0,0) to (10,10), center at (5,5)
        self.assertIsNotNone(center)
        lon, lat = center
        self.assertAlmostEqual(lon, 5.0, places=5)
        self.assertAlmostEqual(lat, 5.0, places=5)

        self.assertIsNotNone(extremes)
        self.assertAlmostEqual(extremes['west'][0], 0.0, places=5)
        self.assertAlmostEqual(extremes['east'][0], 10.0, places=5)
        self.assertAlmostEqual(extremes['south'][1], 0.0, places=5)
        self.assertAlmostEqual(extremes['north'][1], 10.0, places=5)

    def test_very_small_geometry(self):
        """Test with a very small geometry (sub-meter precision)."""
        # Small square, 1 meter on each side (in degrees, approximately)
        small_size = 0.00001  # About 1 meter at equator
        small_polygon = Polygon([
            (0.0, 0.0),
            (small_size, 0.0),
            (small_size, small_size),
            (0.0, small_size),
            (0.0, 0.0)
        ])
        self.work.geometry = GeometryCollection(small_polygon)
        self.work.save()

        center = self.work.get_center_coordinate()
        extremes = self.work.get_extreme_points()

        # Should handle very small geometries
        self.assertIsNotNone(center)
        self.assertIsNotNone(extremes)

        # Center should be in the middle
        lon, lat = center
        self.assertAlmostEqual(lon, small_size / 2, places=8)
        self.assertAlmostEqual(lat, small_size / 2, places=8)

    def test_very_large_geometry(self):
        """Test with a very large geometry spanning multiple continents."""
        # Rectangle spanning from Europe to Asia
        large_polygon = Polygon([
            (0.0, 40.0),    # Europe
            (140.0, 40.0),  # East Asia
            (140.0, 60.0),
            (0.0, 60.0),
            (0.0, 40.0)
        ])
        self.work.geometry = GeometryCollection(large_polygon)
        self.work.save()

        center = self.work.get_center_coordinate()
        extremes = self.work.get_extreme_points()

        # Should handle large geometries
        self.assertIsNotNone(center)
        lon, lat = center
        self.assertAlmostEqual(lon, 70.0, places=5)
        self.assertAlmostEqual(lat, 50.0, places=5)

        self.assertIsNotNone(extremes)
        self.assertAlmostEqual(extremes['west'][0], 0.0, places=5)
        self.assertAlmostEqual(extremes['east'][0], 140.0, places=5)
        self.assertAlmostEqual(extremes['south'][1], 40.0, places=5)
        self.assertAlmostEqual(extremes['north'][1], 60.0, places=5)


class GlobalFeedsFixtureTest(TestCase):
    """Test geometry calculations using complex shapes from the global feeds fixture."""

    fixtures = ['test_data_global_feeds.json']

    def test_triangle_from_fixture(self):
        """Test triangle geometry from global feeds fixture."""
        from works.models import Work

        triangle = Work.objects.get(title__contains="Triangular Survey")
        self.assertIsNotNone(triangle.geometry)

        center = triangle.get_center_coordinate()
        extremes = triangle.get_extreme_points()

        # Verify calculations work
        self.assertIsNotNone(center)
        self.assertIsNotNone(extremes)

        # Center should be within bounding box
        lon, lat = center
        self.assertGreater(lon, 0)  # Mediterranean region
        self.assertGreater(lat, 30)

        # All extremes should be present
        self.assertIsNotNone(extremes['north'])
        self.assertIsNotNone(extremes['south'])
        self.assertIsNotNone(extremes['east'])
        self.assertIsNotNone(extremes['west'])

    def test_pentagon_from_fixture(self):
        """Test pentagon geometry from global feeds fixture."""
        from works.models import Work

        pentagon = Work.objects.get(title__contains="Pentagon Study")
        self.assertIsNotNone(pentagon.geometry)

        center = pentagon.get_center_coordinate()
        extremes = pentagon.get_extreme_points()

        # Verify calculations work
        self.assertIsNotNone(center)
        self.assertIsNotNone(extremes)

        # Pentagon is in Central Europe
        lon, lat = center
        self.assertGreater(lon, 5)
        self.assertLess(lon, 20)
        self.assertGreater(lat, 40)
        self.assertLess(lat, 55)

    def test_concave_polygon_from_fixture(self):
        """Test concave polygon from global feeds fixture."""
        from works.models import Work

        concave = Work.objects.get(title__contains="Concave Polygon")
        self.assertIsNotNone(concave.geometry)

        center = concave.get_center_coordinate()
        extremes = concave.get_extreme_points()

        # Verify calculations work for concave shapes
        self.assertIsNotNone(center)
        self.assertIsNotNone(extremes)

        # Southeast Asia region
        lon, lat = center
        self.assertGreater(lon, 95)
        self.assertLess(lon, 110)

    def test_polygon_with_hole_from_fixture(self):
        """Test polygon with exclusion zone (hole) from global feeds fixture."""
        from works.models import Work

        hole = Work.objects.get(title__contains="Exclusion Zone")
        self.assertIsNotNone(hole.geometry)

        center = hole.get_center_coordinate()
        extremes = hole.get_extreme_points()

        # Verify calculations work for polygons with holes
        self.assertIsNotNone(center)
        self.assertIsNotNone(extremes)

        # Amazon region (negative longitude)
        lon, lat = center
        self.assertLess(lon, -55)
        self.assertGreater(lon, -70)
        self.assertLess(lat, 5)
        self.assertGreater(lat, -10)

    def test_mixed_geometry_from_fixture(self):
        """Test mixed geometry collection from global feeds fixture."""
        from works.models import Work

        mixed = Work.objects.get(title__contains="Multi-site Arctic")
        self.assertIsNotNone(mixed.geometry)

        center = mixed.get_center_coordinate()
        extremes = mixed.get_extreme_points()

        # Verify calculations work for mixed geometries (point + line + polygon)
        self.assertIsNotNone(center)
        self.assertIsNotNone(extremes)

        # Arctic region
        lon, lat = center
        self.assertGreater(lat, 65)  # Arctic latitude

    def test_multipoint_from_fixture(self):
        """Test multipoint geometry from global feeds fixture."""
        from works.models import Work

        multipoint = Work.objects.get(title__contains="Scattered Monitoring")
        self.assertIsNotNone(multipoint.geometry)

        center = multipoint.get_center_coordinate()
        extremes = multipoint.get_extreme_points()

        # Verify calculations work for scattered points
        self.assertIsNotNone(center)
        self.assertIsNotNone(extremes)

        # Pacific region
        lon, lat = center
        self.assertGreater(lon, 150)

    def test_micro_geometry_from_fixture(self):
        """Test very small (sub-meter) geometry from global feeds fixture."""
        from works.models import Work

        micro = Work.objects.get(title__contains="Micro-site")
        self.assertIsNotNone(micro.geometry)

        center = micro.get_center_coordinate()
        extremes = micro.get_extreme_points()

        # Verify calculations work at very small scales
        self.assertIsNotNone(center)
        self.assertIsNotNone(extremes)

        # Verify extreme precision
        lon, lat = center
        # Should have sub-meter precision (many decimal places)
        self.assertGreater(lon, 13.4)
        self.assertLess(lon, 13.5)
        self.assertGreater(lat, 52.51)
        self.assertLess(lat, 52.53)

        # All extreme points should be very close to each other
        north_lon, north_lat = extremes['north']
        south_lon, south_lat = extremes['south']
        # Latitude difference should be very small (meters)
        lat_diff = north_lat - south_lat
        self.assertLess(lat_diff, 0.001)  # Less than ~100 meters

    def test_continental_scale_from_fixture(self):
        """Test very large continental-scale geometry from global feeds fixture."""
        from works.models import Work

        continental = Work.objects.get(title__contains="Continental-scale")
        self.assertIsNotNone(continental.geometry)

        center = continental.get_center_coordinate()
        extremes = continental.get_extreme_points()

        # Verify calculations work at very large scales
        self.assertIsNotNone(center)
        self.assertIsNotNone(extremes)

        # Should span from Americas to Asia
        east_lon, _ = extremes['east']
        west_lon, _ = extremes['west']
        lon_span = east_lon - west_lon
        self.assertGreater(lon_span, 200)  # Spans multiple continents

    def test_star_shaped_polygon_from_fixture(self):
        """Test star-shaped (non-convex complex) polygon from global feeds fixture."""
        from works.models import Work

        star = Work.objects.get(title__contains="Star-shaped")
        self.assertIsNotNone(star.geometry)

        center = star.get_center_coordinate()
        extremes = star.get_extreme_points()

        # Verify calculations work for very complex non-convex shapes
        self.assertIsNotNone(center)
        self.assertIsNotNone(extremes)

        # Arabian Peninsula region
        lon, lat = center
        self.assertGreater(lon, 45)
        self.assertLess(lon, 55)
        self.assertGreater(lat, 18)
        self.assertLess(lat, 25)
