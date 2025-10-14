# Changelog

## [Unreleased]

### Added

- **Temporal extent contribution** (`publications/views_geometry.py`, `work_landing_page.html`)
  - Users can now contribute temporal extent (start/end dates) in addition to spatial extent
  - Added temporal extent contribution form on work landing page with date validation
  - Contribute page now lists publications missing either spatial OR temporal extent
  - Works can be published with only spatial extent, only temporal extent, or both
  - Support for flexible date formats: YYYY, YYYY-MM, or YYYY-MM-DD
  - 12 new tests covering temporal contribution and publishing workflows
  - Updated provenance tracking to log temporal extent contributions
- **Complete status workflow documentation** (`README.md`, `tests/test_status_workflow.py`)
  - Documented all 6 publication statuses: Draft, Harvested, Contributed, Published, Testing, Withdrawn
  - Added detailed workflow transitions and visibility rules
  - 10 new compliance tests verifying status definitions and access controls
  - Tests confirm only Published status is publicly visible
  - Tests verify contribution only allowed for Harvested status
- **Map popup enhancement** (`publications/static/js/main.js`)
  - Added "View Publication Details" button to map popups
  - Links to work landing page for detailed publication view
  - Supports both DOI-based (`/work/<doi>/`) and ID-based (`/work/<id>/`) URLs
  - Styled as Bootstrap primary button for visibility
- **Geometry contribution workflow enhancements**
  - Added support for publications without DOI via ID-based URLs (`/work/<id>/`)
  - ID-based API endpoints for contribution, publishing, and unpublishing
  - Template automatically selects DOI or ID-based URLs based on publication
  - 5 new tests covering ID-based contribution workflow
- **Admin unpublish functionality** (`publications/views_geometry.py`)
  - `unpublish_work()` and `unpublish_work_by_id()` endpoints
  - Changes published works to Draft status with provenance tracking
  - Unpublish button on work landing page for admin users
  - 4 new tests for unpublish workflow
- Test data fixtures with Contributed status records (`fixtures/test_data_optimap.json`)
  - Records 903-904: Contributed publications with DOI and geometry
  - Records 905-906: Publications without DOI (one harvested, one contributed)
  - Realistic provenance information showing contribution workflow
- **RSS/Atom feed harvesting support** (`publications/tasks.py`)
  - `parse_rss_feed_and_save_publications()` function for parsing RSS/Atom feeds
  - `harvest_rss_endpoint()` function for complete RSS harvesting workflow
  - Support for RDF-based RSS feeds (Scientific Data journal)
  - DOI extraction from multiple feed fields (prism:doi, dc:identifier)
  - Duplicate detection by DOI and URL
  - Abstract/description extraction from feed content
- feedparser library integration (v6.0.12)
  - Added to requirements.txt for RSS/Atom feed parsing
  - Supports RSS 1.0/2.0, Atom, and RDF feeds
- Django management command `harvest_journals` enhanced for RSS/Atom feeds
  - Added Scientific Data journal with RSS feed support
  - Support for both OAI-PMH and RSS/Atom feed types
  - Automatic feed type detection based on journal configuration
  - Now supports 4 journals: ESSD, AGILE-GISS, GEO-LEO (OAI-PMH), Scientific Data (RSS)
- Comprehensive RSS harvesting tests (`RSSFeedHarvestingTests`)
  - 7 test cases covering RSS parsing, duplicate detection, error handling
  - Test fixture with sample RDF/RSS feed (`tests/harvesting/rss_feed_sample.xml`)
  - Tests for max_records limit, invalid feeds, and HTTP errors
- Django management command `harvest_journals` for harvesting real journal sources
  - Command-line options for journal selection, record limits, and source creation
  - Detailed progress reporting with colored output
  - Statistics for spatial/temporal metadata extraction
- Integration tests for real journal harvesting (`tests/test_real_harvesting.py`)
  - 6 tests covering ESSD, AGILE-GISS, GEO-LEO, and EssOAr
  - Tests skipped by default (use `SKIP_REAL_HARVESTING=0` to enable)
  - Max records parameter to limit harvesting for testing
- Comprehensive error handling tests for OAI-PMH harvesting (`HarvestingErrorTests`)
  - 10 test cases covering malformed XML, missing metadata, HTTP errors, network timeouts
  - Test fixtures for various error conditions in `tests/harvesting/error_cases/`
  - Verification of graceful error handling and logging
- pytest configuration with custom markers (`pytest.ini`)
  - `real_harvesting` marker for integration tests
  - Configuration for Django test discovery

### Changed

- **Contribution endpoint now accepts both spatial and temporal extents**
  - `contribute_geometry_by_id()` renamed conceptually to handle both extent types
  - Single endpoint can accept geometry, temporal extent, or both in one request
  - Updated error messages to reflect dual-extent support
  - Provenance notes now detail all changes made in single contribution
- **Publishing workflow updated for flexible extent requirements**
  - Harvested publications can be published with spatial extent only, temporal extent only, or both
  - Contributed publications can always be published regardless of extent
  - Updated `publish_work_by_id()` to check for at least one extent type
  - Error message: "Cannot publish harvested publication without spatial or temporal extent"
- **Contribute page query expanded**
  - Now shows publications missing spatial extent OR temporal extent
  - Previously only showed publications missing spatial extent
  - Allows crowdsourcing of both types of metadata
- **Work landing page alerts updated**
  - Dynamic messages show which extent types are missing
  - Conditional UI shows geometry map tools and/or temporal form as needed
  - Context variables `has_geometry` and `has_temporal` passed to template
- **Unified URL structure for work landing pages**
  - Changed ID-based URLs from `/publication/<id>/` to `/work/<id>/`
  - Both DOI-based and ID-based URLs now use `/work/` prefix for consistency
  - Updated all templates, JavaScript, and tests to use new URL structure
  - Legacy `/publication/<id>/` paths no longer exist
- **Refactored views_geometry.py to eliminate code duplication**
  - DOI-based functions now wrap ID-based functions instead of duplicating logic
  - `contribute_geometry()`, `publish_work()`, and `unpublish_work()` translate DOI to ID
  - Core business logic consolidated in `*_by_id()` functions
  - Reduced code from 375 lines to 240 lines (~36% reduction)
  - Easier maintenance with single source of truth for each operation
- **Renamed "Locate" page to "Contribute"** for clarity
  - URL changed from `/locate/` to `/contribute/` (legacy redirect in place)
  - View function renamed: `locate()` → `contribute()`
  - Template renamed: `locate.html` → `contribute.html`
  - Footer link updated: "Locate" → "Contribute"
  - Page title: "Locate Publications" → "Contribute Geolocation Data"
  - Better reflects the crowdsourcing action users perform
- **Completely refactored contribute page layout** to fix text overflow
  - Rewrote CSS from scratch with proper containment strategy
  - Added `min-width: 0` to all flex items (critical for proper shrinking)
  - Added `overflow: hidden` at card, card-body, and card-footer levels
  - Changed DOI breaking from `break-word` to `break-all` for long identifiers
  - Used `<div>` instead of `<br>` for footer metadata (better structure)
  - Reduced button text: "Contribute geospatial metadata" → "Contribute metadata"
  - Text now properly wraps within card boundaries with no overflow
- **Publishing workflow now supports harvested publications with geometry**
  - `publish_work()` and `publish_work_by_id()` functions accept both Contributed and Harvested status
  - Harvested publications can be published directly if they already have geometry
  - Contributed publications can always be published (existing behavior)
  - Updated provenance messages to indicate source status (Contributed vs Harvested)
  - Test updated to verify harvested publication publishing
- **CSS organization improved**
  - Moved all inline CSS from locate.html to central main.css file
  - Better maintainability and consistent styling across pages
- Fixed OAI-PMH harvesting test failures by updating response format parameters
  - Changed from invalid 'structured'/'raw' to valid 'geojson'/'wkt'/'wkb' formats
  - Updated test assertions to expect GeoJSON FeatureCollection
- Fixed syntax errors in `publications/tasks.py`
  - Fixed import statement typo
  - Fixed indentation in `extract_timeperiod_from_html` function
  - Fixed misplaced return statement in `regenerate_geopackage_cache` function
- Fixed test setup method in `tests/test_harvesting.py`
  - Removed incorrect `@classmethod` decorator from `setUp` method
- Fixed `test_regular_harvesting.py` to include `max_records` parameter in mock function
- Updated README.md with comprehensive documentation for:
  - Integration test execution
  - `harvest_journals` management command usage
  - Journal harvesting workflows

### Fixed

- Docker build for geoextent installation (added git dependency to Dockerfile)
- 18 geoextent API test failures due to invalid response format values
- 8 test setup errors in OAI-PMH harvesting tests
- Test harvesting function signature mismatch

### Deprecated

- None.

### Removed

- None.

### Security

- None.

## [0.2.0] - 2025-10-09

### Added

- Work landing page improvements:
  - Clickable DOI links to https://doi.org resolver
  - Clickable source links to journal homepages
  - Link to raw JSON API response
  - Publication title and DOI in HTML `<title>` tag
- Map enhancements on work landing page:
  - Fullscreen control using Leaflet Fullscreen plugin
  - Custom "Zoom to All Features" button
  - Scroll wheel zoom enabled
- Comprehensive test suite for work landing page (9 tests)
- Comprehensive test suite for geoextent API (24 tests)

### Changed

- None.

### Fixed

- None.

### Deprecated

- None.

### Removed

- None.

### Security

- External links (DOI, source, API) now use `target="_blank"` with `rel="noopener"` for security

## [0.1.0] - 2025-04-16

### Added

- Changelog

### Changed

- None.

### Fixed

- None.

### Deprecated

- None.

### Removed

- None.

### Security

- None.
