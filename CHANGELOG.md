# Changelog

## [Unreleased]

### Added

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
