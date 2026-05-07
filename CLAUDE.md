# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

OPTIMAP is a geospatial discovery portal for research articles based on open metadata. Built with Django/GeoDjango and PostgreSQL/PostGIS, it enables users to discover scientific publications through map-based search, temporal filtering, and spatial metadata.

Part of the KOMET project (<https://projects.tib.eu/komet>), continuing from OPTIMETA (<https://projects.tib.eu/optimeta>).

## Companion docs

- [README.md](README.md) — developer / deployer setup, local dev, harvesting CLI.
- [docs/manage.md](docs/manage.md) — admin / operator handbook (Django admin workflows, harvesting management, suggested sections for the rest of the admin surface). When the user asks about how to run, monitor, or troubleshoot a feature **as an admin**, read this first and update it as features change.
- [CHANGELOG.md](CHANGELOG.md) — Keep-a-Changelog-formatted release notes; update on every user-visible change.
- [docs/geoextent_response_formats.md](docs/geoextent_response_formats.md) — geoextent API response shapes.

## Core Architecture

### Django Apps Structure

- **optimap/** - Main Django project settings and URL routing
  - `settings.py` - All configuration via environment variables prefixed with `OPTIMAP_`
  - `.env` file for local config (see `.env.example` for all available parameters)

- **works/** - Main application containing all models, views, and business logic
  - **Models** ([models.py](works/models.py)):
    - `Work` - Core model with spatial (`GeometryCollectionField`) and temporal metadata
    - `Source` - OAI-PMH and RSS/Atom harvesting sources with metadata
    - `HarvestingEvent` - Tracks harvesting jobs
    - `Subscription` - User subscriptions with regional filters (continents/oceans)
    - `GlobalRegion` - Predefined geographic regions (continents and oceans) for feeds and subscriptions
    - `CustomUser` - Extended Django user model
    - `UserProfile` - User preferences (notifications, etc.)
    - `EmailLog` - Email notification tracking
    - `WikidataExportLog` - Wikidata/Wikibase export tracking
    - `BlockedEmail`/`BlockedDomain` - Anti-spam mechanisms
  - **Views** ([views.py](works/views.py)) - Handles passwordless login, subscriptions, data downloads
  - **Harvesting** ([harvesting/](works/harvesting/)) — one module per source type (`oai.py`, `rss.py`, `crossref.py`, `mountain_wetlands.py`, `openalex_source.py`) plus shared helpers (`common.py`, `sessions.py`, `metadata_html.py`, `openalex.py` for enrichment). Public entry points are re-exported from [tasks.py](works/tasks.py) so Django-Q dotted-path schedules keep working.
  - **Other tasks** ([tasks.py](works/tasks.py)) — non-harvest Django-Q tasks: monthly email digest, subscription emails, GeoJSON / GeoPackage cache regeneration, schedule helpers.
  - **API** ([api.py](works/api.py), [viewsets.py](works/viewsets.py), [serializers.py](works/serializers.py)) - DRF REST API at `/api/v1/`
  - **Feeds** ([feeds.py](works/feeds.py), [feeds_geometry.py](works/feeds_geometry.py)) - GeoRSS/GeoAtom feed generation

### Key Technologies

- **GeoDjango** with **PostGIS** for spatial data (SRID 4326)
- **Django REST Framework** with `rest_framework_gis` for geospatial API
- **Django-Q2** for background task scheduling (harvesting, email notifications, data dumps)
- **drf-spectacular** for OpenAPI schema

### Data Flow

1. **Harvesting**: OAI-PMH sources → `HarvestingEvent` → parse XML → create `Work` records with spatial/temporal metadata
2. **API**: Publications exposed via REST API at `/api/v1/works/` with spatial filtering
3. **Feeds**: Dynamic GeoRSS/GeoAtom feeds filtered by region or global
4. **Data Export**: Scheduled tasks generate cached GeoJSON/GeoPackage dumps in `/tmp/optimap_cache/`

## Development Commands

### Docker Development

```bash
# Start all services (app, db, webserver)
docker compose up

# Load test data
docker compose run --entrypoint python app manage.py loaddata fixtures/test_data.json

# Create superuser
docker compose run --entrypoint python app manage.py createsuperuser

# Run migrations manually (normally auto-applied via etc/manage-and-run.sh)
docker compose run --entrypoint python app manage.py migrate

# Collect static files
docker compose run --entrypoint python app manage.py collectstatic --noinput
```

Access at <http://localhost:80/> (note: use `localhost` not `127.0.0.1` to avoid CSRF issues)

### Local Development

```bash
# Setup (once)
python -m venv .venv
source .venv/bin/activate
pip install gdal=="$(gdal-config --version).*"
pip install -r requirements.txt

# Start local PostGIS container
docker run --name optimapDB -p 5432:5432 \
  -e POSTGRES_USER=optimap -e POSTGRES_PASSWORD=optimap \
  -e POSTGRES_DB=optimap -d postgis/postgis:14-3.3

# Apply migrations
python manage.py migrate
python manage.py createcachetable

# Load global regions (required for predefined feeds)
python manage.py load_global_regions

# Start Django-Q cluster (separate terminal, required for harvesting/tasks)
python manage.py qcluster

# Run server (debug mode)
OPTIMAP_DEBUG=True OPTIMAP_CACHE=dummy python manage.py runserver
```

Access at http://127.0.0.1:8000/

### Testing

All tests are always run using the virtual environment defined in `.venv/`; the Docker config is only for deployment of the the app.

```bash
# Install test dependencies
pip install -r requirements-dev.txt

# Run unit tests (fast — excludes network-dependent tests)
python manage.py test tests --exclude-tag=online

# Run UI tests
python -Wa manage.py test tests-ui

# Test with clean output
OPTIMAP_LOGGING_LEVEL=WARNING python manage.py test tests --exclude-tag=online

# Coverage
coverage run --source='publications' --omit='*/migrations/**' manage.py test tests
coverage report --show-missing --fail-under=70
coverage html  # generates htmlcov/
```

#### `online`-tagged tests (network required)

Tests decorated with `@tag('online')` make real HTTP requests to external
services (Copernicus OAI-PMH, GEO-LEO, AGILE-GISS, Zenodo, PANGAEA, etc.).
They live in [tests/test_harvesting.py](tests/test_harvesting.py) and
[tests/test_geoextent.py](tests/test_geoextent.py), and add ~150s+ to a run.
They self-skip when the endpoint is unreachable, but they still spend the
network round-trip, so exclude them by default during iterative development:

```bash
python manage.py test tests --exclude-tag=online   # default dev loop
python manage.py test tests --tag=online           # only the online ones
python manage.py test tests                        # everything (CI does this)
```

**Run the online tests when you change:**

- Anything under [works/harvesting/](works/harvesting/) — OAI-PMH parsing, RSS/Atom,
  Crossref, mountain-wetlands, OpenAlex (both `openalex.py` enrichment and
  `openalex_source.py` as-source harvester), or `common.py`/`sessions.py`/
  `metadata_html.py` helpers. Real endpoints catch schema drift and parser
  regressions that fixtures don't.
- The `harvest_*` task entry points re-exported from [works/tasks.py](works/tasks.py).
- The geoextent remote-extraction code path
  ([works/views.py](works/views.py) `geoextent_extract_remote`, related
  serializers, and the `extract-remote` / `extract-batch` endpoints) — these
  exercise live DOI resolvers and repository APIs.
- HTTP session / retry / timeout configuration shared by the above.

**Separately:** [tests/test_harvesting_online.py](tests/test_harvesting_online.py)
uses `@unittest.skipIf(settings.TEST_HARVESTING_ONLINE != True, …)` instead of
the `online` tag and is gated by the `OPTIMAP_TEST_HARVESTING_ONLINE=True`
environment variable. Set it when you want those legacy live-harvest checks
too:

```bash
OPTIMAP_TEST_HARVESTING_ONLINE=True python manage.py test tests.test_harvesting_online
```

### Django Management Commands

#### Standard Django Commands

```bash
# Database operations
python manage.py makemigrations              # Create new migrations (should detect no changes normally)
python manage.py migrate                     # Apply database migrations
python manage.py showmigrations              # List all migrations and their status
python manage.py sqlmigrate publications 0001  # Show SQL for a specific migration

# User management
python manage.py createsuperuser             # Create admin user interactively
python manage.py createsuperuser --username=optimap --email=admin@optimap.science
python manage.py changepassword <username>   # Change user password

# Static files
python manage.py collectstatic --noinput     # Collect static files to STATIC_ROOT
python manage.py findstatic <filename>       # Find location of static file

# Cache
python manage.py createcachetable            # Create database cache table (required on setup)

# Data management
python manage.py dumpdata <app.Model>        # Export data as JSON
python manage.py loaddata <fixture.json>     # Import data from JSON fixture
python manage.py flush                       # Clear all data from database (careful!)

# Shell access
python manage.py shell                       # Django shell with models loaded
python manage.py shell -c "from works.tasks import regenerate_geojson_cache; regenerate_geojson_cache()"
python manage.py dbshell                     # Direct PostgreSQL shell

# Development server
python manage.py runserver                   # Start dev server on 127.0.0.1:8000
python manage.py runserver 0.0.0.0:8000     # Start on all interfaces (Docker)
OPTIMAP_DEBUG=True python manage.py runserver  # With debug mode

# Testing
python manage.py test                        # Run all tests
python manage.py test tests                  # Run unit tests only
python manage.py test tests-ui               # Run UI tests only
python manage.py test tests.test_geo_data    # Run specific test module
python manage.py test tests.test_geoextent   # Run geoextent API integration tests
python -Wa manage.py test                    # Show deprecation warnings
```

#### Custom OPTIMAP Commands

Located in [works/management/commands/](works/management/commands/)

```bash
# Global regions setup
python manage.py load_global_regions
# Loads predefined continent and ocean geometries into GlobalRegion model
# Required for global feeds and regional subscriptions - run once after initial setup

# Data export scheduling
python manage.py schedule_geojson
# Adds GeoJSON/GeoPackage regeneration task to Django-Q schedule
# Creates recurring task to refresh data dumps every 6 hours

# Regenerate data dumps on-demand (synchronous, no Q cluster needed)
python manage.py regenerate_data_dumps
# Runs the umbrella regen and writes GeoJSON + GeoPackage + CSV to /tmp/optimap_cache/
python manage.py regenerate_data_dumps --format csv
# Restrict to a single format (geojson | gpkg | csv)
python manage.py regenerate_data_dumps --dry-run
# Report what would be regenerated without writing

# Harvest from real journals
python manage.py harvest_journals --list
# Lists all available journal sources (OAI-PMH and RSS/Atom)
python manage.py harvest_journals --all --max-records 50
# Harvests from all configured journals with record limit
python manage.py harvest_journals --journal essd --journal geo-leo
# Harvests from specific journals by identifier
# Supports: essd, agile-giss, geo-leo, eartharxiv, scientific-data

# Source synchronization
python manage.py sync_source_metadata
# Syncs metadata from configured OAI-PMH sources
# Updates Source model with latest information from endpoints

# OpenAlex journal updates
python manage.py update_openalex_journals
# Fetches and updates journal metadata from OpenAlex API
# Enriches Source records with additional journal information

# Reset harvest schedules
python manage.py reset_harvest_schedules
# Rebuilds the recurring `Harvest Source <id>` schedules with a deferred
# next_run (and stagger by default), recovering from a state where every
# source's schedule fires at once. Flags: --dry-run, --no-stagger, --clear-manual.

# Clear Django caches
python manage.py clear_caches
# Clears all configured Django cache backends (`memory`, `default`, `dummy`).
# Django ships no built-in `clearcache` (see SO #5942759); this command
# makes the operation explicit, idempotent, and scriptable for deploy hooks.
# Flags: --cache <alias> (repeatable, clear only those), --exclude <alias>
# (repeatable, clear all except those — `--exclude default` preserves
# in-flight login-magic / email-confirmation tokens), --dry-run.
# See docs/manage.md → "Manage data dumps and caches" for which backend
# stores what and when to clear which.
```

#### Django-Q Task Management

```bash
# Start task worker (required for async operations)
python manage.py qcluster
# Runs background worker to process harvesting jobs, email sending, data exports
# Keep running in separate terminal during development

# Monitor tasks
python manage.py qmonitor      # Live dashboard of task queue
python manage.py qinfo         # Show cluster statistics and status

# Manual task management via Django shell
python manage.py shell
>>> from django_q.models import Schedule
>>> Schedule.objects.all()  # List scheduled tasks
>>> from django_q.tasks import async_task
>>> async_task('publications.tasks.regenerate_geojson_cache')  # Queue a task
```

### Manual Data Operations

```bash
# Create test data dump
python manage.py dumpdata --exclude=auth --exclude=contenttypes | jq > fixtures/test_data.json

# Load fixtures
python manage.py loaddata fixtures/test_data_optimap.json
python manage.py loaddata fixtures/test_data_partners.json
python manage.py loaddata fixtures/test_data_global_feeds.json

# Manually regenerate GeoJSON/GeoPackage cache (without Django-Q)
python manage.py shell -c "from works.tasks import regenerate_geojson_cache; regenerate_geojson_cache()"
```

## Important Patterns

### Configuration

All deployment-specific config uses `OPTIMAP_*` environment variables loaded from `.env` or environment. See [optimap/.env.example](optimap/.env.example).

### Spatial Data

- All geometries use `GeometryCollectionField` with SRID 4326
- WKT format for manual geometry input (use https://wktmap.com/ for creation)
- Spatial metadata extracted from HTML `<meta name="DC.SpatialCoverage">` tags during harvesting

### Harvesting Flow

1. Create/configure `Source` in admin with OAI-PMH URL, RSS/Atom feed URL, Crossref prefix, MaRESS API URL, or OpenAlex source identifier (`S<digits>` on `openalex_id`; the public `openalex_url` is now a derived property).
2. Django-Q task creates `HarvestingEvent` (or use `harvest_journals` command for direct harvesting)
3. Fetch XML/RSS/JSON → parse → extract DOI, spatial, temporal metadata → save `Work` records with status `h` (Harvested)
4. Track status in `HarvestingEvent.status` (pending/in_progress/completed/failed)
5. Works with spatial/temporal metadata can be published directly, or users can contribute missing metadata
6. OpenAlex enrichment: Automatically fetches additional metadata (authors, keywords, topics) when DOI is available — runs inside the OAI-PMH harvester via `works.harvesting.openalex.build_openalex_fields`. Distinct from the **`openalex` source type** (`works.harvesting.openalex_source`), which uses OpenAlex as the *primary* harvest origin (see [docs/manage.md](docs/manage.md) → "OpenAlex-as-source"). The OpenAlex source harvester does not fetch publisher landing pages — OpenAlex carries no spatial/temporal coverage and the journals it currently targets (e.g. AGILE-GISS) don't expose any in their HTML either.

### Authentication

- Passwordless "magic link" system based on own implementation
- Users receive login token via email (10-minute expiration)
- Email confirmation for account changes
- CSRF tokens required - use `localhost` domain during development (not 127.0.0.1)

### Testing Notes

- UI tests use Helium/Selenium (set `headless=False` for debugging)
- UI tests use Django cache for token management (see test_emailchange.py, test_accountdeletion.py, test_loginresponse.py)
- Tests create mock tokens in `setUp()` and retrieve them from cache during test execution
- Test data fixtures in `fixtures/` directory
- Use `-Wa` flag to show deprecation warnings

## Common Gotchas

- **CSRF errors during login**: Switch to `localhost:8000` instead of `127.0.0.1:8000`
- **Migrations on startup**: Applied automatically via `etc/manage-and-run.sh` in Docker
- **Debug mode**: Default is `OPTIMAP_DEBUG=False` - set explicitly for development
- **Email debugging**: Set `EMAIL_BACKEND=django.core.mail.backends.console.EmailBackend` in `.env`
- **Django-Q cluster**: Must be running separately for harvesting/scheduled tasks to execute
- **Data dumps retention**: Controlled by `OPTIMAP_DATA_DUMP_RETENTION` (default: 3)

## File Structure Highlights

```
optimap/
├── optimap/          # Django project settings
├── works/     # Main app (models, views, tasks, API)
│   ├── management/commands/  # Custom Django commands
│   ├── static/       # Frontend assets, logos
│   └── templates/    # Django templates
├── tests/            # Unit tests
├── tests-ui/         # Selenium UI tests
├── fixtures/         # Test data JSON
├── etc/              # Deployment scripts (manage-and-run.sh)
├── static/           # Collected static files (generated)
└── docker-compose.yml / docker-compose.deploy.yml
```

## Key Features & UI Components

### Navigation

- **Burger Menu** - Unified hamburger menu (☰) in top bar with links to all main pages
- **User Menu** - User icon in top bar with login/logout and user settings
- **Footer** - Sitemap, About/Contact, Privacy, Data License links

### Map Features

- **Interactive Map** - Main map with publication markers using Leaflet
- **Zoom-to-All Control** - Quick button to fit all publications in view (available on all maps)
- **Gazetteer/Geocoding Search** - Search for locations by name (Nominatim, GeoNames, Photon support)
- **Global Regions Layer** - Toggle-able overlay showing continent and ocean boundaries
- **Paginated Popups** - Cycle through multiple overlapping publications with Previous/Next navigation
- **Geometry Highlighting** - Visual feedback when selecting publications (gold/orange colors)

### Pages

- `/` - Main map and timeline of publications
- `/works/list/` - Browse all works with pagination (configurable page size)
- `/work/<id>/` or `/work/<doi>/` - Individual work landing page
- `/contribute/` - Crowdsourced spatial/temporal metadata contribution (paginated)
- `/subscriptions/` - Regional subscription management (continents and oceans)
- `/geoextent/` - Geoextent extraction web UI
- `/pages` - Human-readable sitemap with organized page list
- `/feeds/` - Feed landing pages for global and regional RSS/Atom feeds

### Workflows

- **Publication Status**: Draft → Harvested → Contributed → Published (with Testing and Withdrawn states)
- **User Contribution**: Users can add spatial and/or temporal extent to harvested publications
- **Regional Subscriptions**: Users receive email notifications for new publications in selected regions
- **Admin Publishing**: Admins review contributions and publish works

## API & Endpoints

> **Keep the API docs in sync with the code.** Whenever you add, remove, or change a REST
> endpoint — including new `@action` methods, new ViewSets, new function-based `@api_view`
> handlers, new query parameters, new response shapes, or new error paths — also update
> the schema annotations so `/api/schema/ui/` keeps reflecting reality. Concretely:
> - Decorate every public endpoint with `@extend_schema(summary=…, tags=[…], request=…, responses={200: …, 4xx/5xx: OpenApiResponse(…)})`. Use `@extend_schema_view` on ViewSets to set per-method summaries.
> - Tag each endpoint with one of the `TAGS` declared in `optimap/settings.py:SPECTACULAR_SETTINGS` (Works / Sources / Subscriptions / Global regions / Geoextent / Gazetteer / Downloads). If a new endpoint doesn't fit any tag, add a tag entry alongside the others so Redoc gives it a sidebar section.
> - Document every error status the view can actually return — `404`, `400`, `401`/`403`, `413`, `500`, etc. (cross-check against `tests/test_*.py` assertions on `response.status_code` and explicit `Response(..., status=...)` returns in the view).
> - For function-based Django views that should appear in the docs (downloads, gazetteer proxies, …), wrap them in `@api_view([…])` + `@permission_classes([...])` so drf-spectacular can pick them up.
> - Run `python manage.py spectacular --file /tmp/optimap_schema.yaml` after the change; it must report `Errors: 0` (warnings are tolerable but should not regress).
> - Update the Markdown intro in `SPECTACULAR_SETTINGS['DESCRIPTION']` (and the relevant `TAGS` description) when conventions change (auth, pagination, filtering, new endpoint families).

- `/api/v1/` - REST API root (see `/api/schema/ui/` for OpenAPI docs)
- `/admin/` - Django admin interface
- `/download/geojson/` - Download full publication dataset as GeoJSON
- `/download/geopackage/` - Download as GeoPackage
- `/download/csv/` - Download as CSV (one row per work, `WKT` geometry column in OGC Simple Features)
- `/feed/georss/` - Global GeoRSS feed
- `/feeds/georss/<slug>/` - Region-filtered GeoRSS feed (continents and oceans)
- `/sitemap-works.xml` - Sitemap for all published works
- `/sitemap-feeds.xml` - Sitemap for all regional feeds
- `/geoextent/` - Geoextent extraction web UI (interactive tool for file upload and remote resource extraction)

### Geoextent API Endpoints

#### Public API - No authentication required

All geoextent endpoints return valid GeoJSON FeatureCollections by default, matching the geoextent CLI output format.

- `/api/v1/geoextent/extract/` - Extract spatial/temporal extent from uploaded file
  - Method: POST with multipart/form-data
  - Parameters: file, bbox, tbox, convex_hull, response_format, placename, gazetteer
  - Returns: GeoJSON FeatureCollection with `geoextent_extraction` metadata

- `/api/v1/geoextent/extract-remote/` - Extract extent from remote repositories
  - Methods: GET or POST (same URL)
  - POST: JSON body with `identifiers` array
  - GET: URL parameters with comma-separated `identifiers`
  - Supports: Zenodo, PANGAEA, OSF, Figshare, Dryad, GFZ Data Services, Dataverse
  - Parameters: identifiers, bbox, tbox, convex_hull, response_format, placename, gazetteer, file_limit, size_limit_mb
  - Uses geoextent's native multi-identifier support with automatic extent merging
  - Parallel downloads controlled by `GEOEXTENT_DOWNLOAD_WORKERS` setting
  - Example GET: `/api/v1/geoextent/extract-remote/?identifiers=10.5281/zenodo.4593540&bbox=true&tbox=true`
  - Example POST: `{"identifiers": ["10.5281/zenodo.4593540"], "bbox": true, "tbox": true}`

- `/api/v1/geoextent/extract-batch/` - Batch processing of multiple files
  - Method: POST with multipart/form-data (multiple files)
  - Parameters: files[], bbox, tbox, convex_hull, response_format, placename, gazetteer, size_limit_mb
  - Uses geoextent's `fromDirectory` for native extent combination
  - Returns: GeoJSON FeatureCollection with combined extent and individual features

**Response Formats** (`response_format` parameter):

- `geojson` (default) - Valid GeoJSON FeatureCollection matching CLI output
  - Structure: `{"type": "FeatureCollection", "features": [...], "geoextent_extraction": {...}}`
  - Temporal extent in feature properties as `tbox` (not `temporal_extent`)
- `wkt` - WKT (Well-Known Text) string with metadata
  - Structure: `{"wkt": "POLYGON(...)", "crs": "EPSG:4326", "tbox": [...], "geoextent_extraction": {...}}`
- `wkb` - WKB (Well-Known Binary) hex string with metadata
  - Structure: `{"wkb": "0103...", "crs": "EPSG:4326", "tbox": [...], "geoextent_extraction": {...}}`

See [docs/geoextent_response_formats.md](docs/geoextent_response_formats.md) for detailed examples.

**Metadata Structure** (`geoextent_extraction`):

Property names match geoextent CLI output to avoid confusion:

- `version` - Geoextent library version
- `inputs` - List of input identifiers/filenames
- `statistics.files_processed` - Number of files processed
- `statistics.files_with_extent` - Number of files with valid extent
- `statistics.total_size` - Total size (e.g., "2.71 MiB")
- `format` - Source format (e.g., "remote", "geojson")
- `crs` - Coordinate reference system
- `extent_type` - "bounding_box" or "convex_hull"

**HTTP Status Codes:**

- `200 OK` - Successful extraction
- `400 Bad Request` - Invalid parameters
- `413 Request Entity Too Large` - File too large
- `500 Internal Server Error` - Processing error

Error responses: `{"error": "message"}` (no `success: false` property)

**Supported Input Formats:**
GeoJSON, GeoTIFF, Shapefile, GeoPackage, KML, GML, GPX, FlatGeobuf, CSV (with lat/lon)

**Gazetteers:** Nominatim (default), GeoNames (requires username), Photon

**Known Issues:**

- **Coordinate order bug in geoextent.fromRemote()**: The geoextent library's `fromRemote()` function returns bounding boxes in `[minLat, minLon, maxLat, maxLon]` format instead of the GeoJSON standard `[minLon, minLat, maxLon, maxLat]`. This affects remote extractions only (not file uploads). This needs to be fixed upstream in the geoextent library. Until fixed, remote extraction coordinates will be in the wrong order.

### Geoextent Web UI

Interactive web interface at [/geoextent](works/templates/geoextent.html) for extracting geospatial/temporal extents from data files.

**Features:**

- File upload (single or batch) with size validation
- Remote resource extraction via DOI/URL (comma-separated)
- Interactive Leaflet map preview with clickable features
- Parameter customization (bbox, tbox, convex_hull, placename, gazetteer)
- Response format selection (GeoJSON, WKT, WKB)
- Download results in selected format
- Client-side file size validation against server limits
- Error handling with informative messages
- Documentation section with supported formats and providers
- Use *sentence case* for all headlines and fields

**Implementation:**

- View: [works/views.py](works/views.py) - `geoextent()` function
  - Uses `geoextent.lib.features.get_supported_features()` to dynamically load supported formats and providers
  - No hardcoded format lists - always reflects current geoextent capabilities
- Template: [works/templates/geoextent.html](works/templates/geoextent.html)
  - Uses Fetch API for AJAX requests (jQuery slim doesn't include $.ajax)
  - Interactive file management with add/remove functionality
  - Multiple file selection from different locations
  - CSRF token handling for secure POST requests
- Uses existing jQuery (slim) and Bootstrap (no additional libraries)
- Map integration via existing Leaflet setup
- API calls to `/api/v1/geoextent/` endpoints
- UI tests: [tests-ui/test_geoextent.py](tests-ui/test_geoextent.py)

**Configuration:**

Size limits passed from Django settings:

- `GEOEXTENT_MAX_FILE_SIZE_MB` - Single file upload limit
- `GEOEXTENT_MAX_BATCH_SIZE_MB` - Total batch upload limit
- `GEOEXTENT_MAX_DOWNLOAD_SIZE_MB` - Remote resource download limit

**Navigation:**

- Footer link added to [works/templates/footer.html](works/templates/footer.html)
- URL route: `path("geoextent/", views.geoextent, name="geoextent")` in [works/urls.py](works/urls.py)

## Version Management

Version is maintained in [optimap/\_\_init\_\_.py](optimap/__init__.py). Follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html). Update [CHANGELOG.md](CHANGELOG.md) following [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) format.
