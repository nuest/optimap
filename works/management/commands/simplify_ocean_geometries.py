import os
import json
from django.conf import settings
from django.core.management.base import BaseCommand
from django.contrib.gis.gdal import DataSource
from shapely import wkt
from shapely.geometry import shape, mapping, Polygon, MultiPolygon
from shapely.ops import unary_union

# Use configurable data directory if set, otherwise fall back to command directory
COMMAND_DIR = os.path.dirname(__file__)
DATA_DIR = settings.GLOBAL_REGIONS_DATA_DIR or COMMAND_DIR

INPUT_GPKG = "goas_v01.gpkg"
OUTPUT_GEOJSON = "goas_v01_simplified.geojson"


class Command(BaseCommand):
    help = "Simplify ocean geometries by removing small holes while preserving large islands"

    def add_arguments(self, parser):
        parser.add_argument(
            '--percentile',
            type=float,
            default=80.0,
            help='Percentile threshold for hole removal (default: 80.0, removes smallest 80%% of holes)'
        )
        parser.add_argument(
            '--tolerance',
            type=float,
            default=0.05,
            help='Tolerance for geometry simplification (default: 0.1)'
        )
        parser.add_argument(
            '--preserve-topology',
            action='store_true',
            default=False,
            help='Preserve topology during simplification - VERY slow if activated (default: False)'
        )

    def handle(self, *args, **options):
        input_path = os.path.join(DATA_DIR, INPUT_GPKG)
        output_path = os.path.join(DATA_DIR, OUTPUT_GEOJSON)
        percentile = options['percentile']
        tolerance = options['tolerance']
        preserve_topology = options['preserve_topology']

        if not os.path.exists(input_path):
            self.stdout.write(
                self.style.ERROR(f"Input file not found: {input_path}")
            )
            return

        self.stdout.write(f"Reading GeoPackage from {input_path}...")

        # DataSource does not support automatic closing, deleting object manually below
        # See https://docs.djangoproject.com/en/5.2/ref/contrib/gis/gdal/#datasource
        ds = DataSource(input_path)
        layer = ds[0]

        self.stdout.write(f"Found {len(layer)} features in layer '{layer.name}'")
        self.stdout.write(f"Fields: {layer.fields}")
        self.stdout.write(f"Simplification tolerance: {tolerance}")
        self.stdout.write(f"Preserve topology: {preserve_topology}")
        self.stdout.write(f"Hole removal percentile: {percentile}%")

        # First pass: collect all hole areas to calculate threshold
        self.stdout.write("\nAnalyzing hole sizes across all geometries...")
        all_hole_areas = []

        for feat in layer:
            geom = feat.geom.geos
            geom_wkt = geom.wkt
            shapely_geom = wkt.loads(geom_wkt)

            # Simplify geometry first
            self.stdout.write(f"Simplifying geometry for '{layer.name}' ...")
            shapely_geom = shapely_geom.simplify(tolerance, preserve_topology=preserve_topology)

            self.stdout.write(f"Collecting holes for '{layer.name}' ...")
            # Collect hole areas from all polygons
            if shapely_geom.geom_type == 'Polygon':
                for interior in shapely_geom.interiors:
                    hole_poly = Polygon(interior)
                    all_hole_areas.append(hole_poly.area)
            elif shapely_geom.geom_type == 'MultiPolygon':
                for poly in shapely_geom.geoms:
                    for interior in poly.interiors:
                        hole_poly = Polygon(interior)
                        all_hole_areas.append(hole_poly.area)

        if not all_hole_areas:
            self.stdout.write(self.style.WARNING("No holes found in geometries. Saving unchanged geometries..."))
            eps = 0
        else:
            all_hole_areas.sort()
            total_holes = len(all_hole_areas)
            threshold_index = int(total_holes * (percentile / 100.0))

            if threshold_index >= total_holes:
                threshold_index = total_holes - 1

            eps = all_hole_areas[threshold_index] if threshold_index >= 0 else 0

            self.stdout.write(f"Total holes found: {total_holes}")
            self.stdout.write(f"Hole area range: {all_hole_areas[0]:.6f} to {all_hole_areas[-1]:.6f}")
            self.stdout.write(f"Calculated eps (area threshold at {percentile}th percentile): {eps:.6f}")
            self.stdout.write(f"This will remove approximately {threshold_index + 1} holes and preserve {total_holes - threshold_index - 1} holes\n")

        del ds  # We cannot close the source but can only rely on the GC

        # Second pass: process geometries with calculated eps
        ds = DataSource(input_path)
        layer = ds[0]

        features = []

        for i, feat in enumerate(layer):
            # Get the original geometry
            geom = feat.geom.geos
            geom_wkt = geom.wkt
            shapely_geom = wkt.loads(geom_wkt)

            # Collect all attributes/properties
            properties = {}
            for field_name in layer.fields:
                properties[field_name] = feat.get(field_name)

            feature_name = properties.get('name', 'unnamed')

            # Step 1: Simplify geometry
            shapely_geom = shapely_geom.simplify(tolerance, preserve_topology=preserve_topology)

            # Count holes after simplification
            original_hole_count = 0
            if shapely_geom.geom_type == 'Polygon':
                original_hole_count = len(list(shapely_geom.interiors))
            elif shapely_geom.geom_type == 'MultiPolygon':
                original_hole_count = sum(len(list(poly.interiors)) for poly in shapely_geom.geoms)

            # Step 2: Apply hole removal
            simplified_geom = self.remove_small_holes(shapely_geom, eps)

            # Count remaining holes
            remaining_hole_count = 0
            if simplified_geom.geom_type == 'Polygon':
                remaining_hole_count = len(list(simplified_geom.interiors))
            elif simplified_geom.geom_type == 'MultiPolygon':
                remaining_hole_count = sum(len(list(poly.interiors)) for poly in simplified_geom.geoms)

            holes_removed = original_hole_count - remaining_hole_count

            # Create GeoJSON feature with simplified geometry
            feature = {
                "type": "Feature",
                "geometry": mapping(simplified_geom),
                "properties": properties
            }
            features.append(feature)

            self.stdout.write(
                f"  Feature {i + 1}: {feature_name} - "
                f"Removed {holes_removed} holes ({original_hole_count} -> {remaining_hole_count})"
            )

        del ds  # We cannot close the source but can only rely on the GC

        # Create GeoJSON FeatureCollection
        geojson = {
            "type": "FeatureCollection",
            "features": features
        }

        # Write to output file
        with open(output_path, "w") as f:
            json.dump(geojson, f, indent=2)

        self.stdout.write(
            self.style.SUCCESS(
                f"\nSuccessfully wrote {len(features)} simplified geometries to {output_path}"
            )
        )

    def remove_small_holes(self, geom, eps):
        """
        Remove holes smaller than eps from polygon geometries.
        Based on: https://gis.stackexchange.com/a/409398
        """
        if eps == 0:
            return geom

        if geom.geom_type == 'Polygon':
            return self.remove_holes_from_polygon(geom, eps)
        elif geom.geom_type == 'MultiPolygon':
            polygons = [self.remove_holes_from_polygon(poly, eps) for poly in geom.geoms]
            return MultiPolygon(polygons)
        else:
            # For other geometry types, return unchanged
            return geom

    def remove_holes_from_polygon(self, polygon, eps):
        """
        Remove holes smaller than eps from a single polygon.
        """
        if not polygon.interiors:
            return polygon

        # Filter holes: keep only those larger than eps
        kept_interiors = []
        for interior in polygon.interiors:
            hole_poly = Polygon(interior)
            if hole_poly.area > eps:
                kept_interiors.append(interior)

        # Create new polygon with filtered holes
        return Polygon(polygon.exterior, holes=kept_interiors)
