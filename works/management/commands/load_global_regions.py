import os
import io
import zipfile
import shutil
import urllib.request
import urllib.parse
from django.conf import settings
from works.models import GlobalRegion
from django.core.management.base import BaseCommand
from django.contrib.gis.gdal import DataSource

# Use configurable data directory if set, otherwise fall back to command directory
COMMAND_DIR = os.path.dirname(__file__)
DATA_DIR = settings.GLOBAL_REGIONS_DATA_DIR or COMMAND_DIR

CONTINENTS_URL = (
    "https://services.arcgis.com/P3ePLMYs2RVChkJx/arcgis/rest/services/"
    "World_Continents/FeatureServer/0/query"
    "?where=1%3D1&outFields=*&f=geojson"
)  # Esri Hub World Continents Feature Service
CONTINENTS_FILE = "world_continents.geojson"

OCEANS_DOWNLOAD_URL = "https://marineregions.org/download_file.php?name=GOaS_v1_20211214_gpkg.zip"
OCEANS_GPKG_FILE = "goas_v01.gpkg"
OCEANS_SIMPLIFIED_FILE = "goas_v01_simplified.geojson"
OCEANS_CITATION = (
    "Flanders Marine Institute (2021). Global Oceans and Seas, version 1. "
    "Available online at https://www.marineregions.org/. "
    "https://doi.org/10.14284/542"
)
OCEANS_DOI = "https://doi.org/10.14284/542"


class Command(BaseCommand):
    help = "Load 7 continents (Esri Hub) and 10 oceans (MarineRegions Global Oceans and Seas v1) into GlobalRegion"

    def handle(self, *args, **options):
        self.stdout.write(f"Looading global regions…")

        # Ensure data directory exists if it's a custom path
        if settings.GLOBAL_REGIONS_DATA_DIR and not os.path.exists(DATA_DIR):
            self.stdout.write(f"Creating data directory: {DATA_DIR}")
            os.makedirs(DATA_DIR, exist_ok=True)

        continents_path = os.path.join(DATA_DIR, CONTINENTS_FILE)

        if os.path.exists(continents_path):
            self.stdout.write(f"File {continents_path} already exists, not downloading data again - delete it to renew the global regions")
        else:
            self.stdout.write("Downloading Esri World Continents…")
            with urllib.request.urlopen(CONTINENTS_URL) as resp, open(continents_path, "wb") as out:
                shutil.copyfileobj(resp, out)

        # DataSource does not support automatic closing, deleting object manually below, see https://docs.djangoproject.com/en/5.2/ref/contrib/gis/gdal/#datasource
        ds = DataSource(continents_path)
        layer = ds[0]
        for feat in layer:
            name = feat.get("CONTINENT") or feat.get(
                "Name") or feat.get("continent")
            geom = feat.geom.geos

            obj, created = GlobalRegion.objects.update_or_create(
                name=name,
                region_type=GlobalRegion.CONTINENT,
                defaults={
                    "geom":       geom,
                    "source_url": CONTINENTS_URL,
                    "license":    "https://www.arcgis.com/sharing/rest/content/items/57c1ade4fa7c4e2384e6a23f2b3bd254/info/metadata/metadata.xml?format=default&output=html",
                }
            )
            verb = "Created" if created else "Updated"
            self.stdout.write(f"{verb} continent '{obj.name}'")
        del ds  # We cannot close the source but can only rely on the GC

        oceans_gpkg_path = os.path.join(DATA_DIR, OCEANS_GPKG_FILE)
        oceans_simplified_path = os.path.join(DATA_DIR, OCEANS_SIMPLIFIED_FILE)

        # Download and extract if GeoPackage doesn't exist
        gpkg_downloaded = False
        if os.path.exists(oceans_gpkg_path):
            self.stdout.write(f"File {oceans_gpkg_path} already exists, not downloading data again - delete it to renew the global regions")
        else:
            self.stdout.write("Downloading MarineRegions Global Oceans and Seas…")

            # Download ZIP file with form data (required by Marine Regions)
            form_data = urllib.parse.urlencode({
                'name': 'OPTIMAP Project TU Dresden',
                'organisation': 'TU Dresden',
                'email': 'komet@tu-dresden.de',
                'country': 'Germany',
                'user_category': 'academia',
                'purpose_category': 'Research',
                'agree': '1'
            }).encode('utf-8')

            req = urllib.request.Request(OCEANS_DOWNLOAD_URL, data=form_data)
            with urllib.request.urlopen(req) as resp:
                zip_data = resp.read()

            # Extract GeoPackage from ZIP
            self.stdout.write("Extracting GeoPackage from ZIP…")
            with zipfile.ZipFile(io.BytesIO(zip_data)) as zf:
                # Extract the .gpkg file
                for name in zf.namelist():
                    if name.endswith('.gpkg'):
                        zf.extract(name, DATA_DIR)
                        # Rename if necessary
                        extracted_path = os.path.join(DATA_DIR, name)
                        if extracted_path != oceans_gpkg_path:
                            shutil.move(extracted_path, oceans_gpkg_path)
                        break

            gpkg_downloaded = True

            # Delete old simplified file if GeoPackage was just downloaded
            if os.path.exists(oceans_simplified_path):
                self.stdout.write(f"Removing old simplified file {OCEANS_SIMPLIFIED_FILE} (GeoPackage was updated)")
                os.remove(oceans_simplified_path)

        # Simplify geometries if simplified file doesn't exist
        if os.path.exists(oceans_simplified_path):
            self.stdout.write(f"Simplified file {oceans_simplified_path} already exists, not re-simplifying - delete it to regenerate")
        else:
            self.stdout.write("\nSimplifying ocean geometries...")
            tolerance = settings.OCEAN_SIMPLIFICATION_TOLERANCE
            percentile = settings.OCEAN_SIMPLIFICATION_PERCENTILE

            self.stdout.write(f"Using tolerance={tolerance}, percentile={percentile}")

            # Call the simplify_ocean_geometries command
            from django.core.management import call_command
            call_command('simplify_ocean_geometries',
                        tolerance=tolerance,
                        percentile=percentile)

            self.stdout.write(self.style.SUCCESS("Ocean geometry simplification complete\n"))

        # Load from simplified GeoJSON file
        # DataSource does not support automatic closing, deleting object manually below, see https://docs.djangoproject.com/en/5.2/ref/contrib/gis/gdal/#datasource
        ds = DataSource(oceans_simplified_path)
        layer = ds[0]

        fields = layer.fields
        self.stdout.write(f"Loading simplified ocean data from {OCEANS_SIMPLIFIED_FILE}")
        self.stdout.write(f"Fields: {fields}")

        # Determine the name field
        if "name" in fields:
            name_field = "name"
        elif "Name" in fields:
            name_field = "Name"
        else:
            raise RuntimeError(f"No obvious name field; found {fields}")

        # Load all ocean/sea features
        for feat in layer:
            name = feat.get(name_field)
            if not name:
                continue

            geom = feat.geom.geos

            # Convert Polygon to MultiPolygon if needed (GlobalRegion expects MultiPolygon)
            from django.contrib.gis.geos import MultiPolygon, Polygon
            if isinstance(geom, Polygon):
                geom = MultiPolygon([geom])

            obj, created = GlobalRegion.objects.update_or_create(
                name=name,
                region_type=GlobalRegion.OCEAN,
                defaults={
                    "geom":       geom,
                    "source_url": OCEANS_DOI,
                    "license":    "https://creativecommons.org/licenses/by/4.0/",
                }
            )
            verb = "Created" if created else "Updated"
            self.stdout.write(f"{verb} ocean '{obj.name}'")
        del ds  # We cannot close the source but can only rely on the GC
