# Changelog

All notable changes to OPTIMAP are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- **Geoextent API** - REST API exposing the [geoextent library](https://github.com/nuest/geoextent) for extracting geospatial and temporal extents from various file formats and remote repositories. Features include:
  - `/api/v1/geoextent/extract/` - Extract from uploaded files (GeoJSON, GeoTIFF, Shapefile, GeoPackage, KML, CSV, etc.)
  - `/api/v1/geoextent/extract-remote/` - Extract from remote repositories (Zenodo, PANGAEA, OSF, Figshare, Dryad, GFZ Data Services, Dataverse)
  - `/api/v1/geoextent/extract-batch/` - Batch processing of multiple files with combined extent
  - Multiple response formats: GeoJSON (default), WKT, WKB
  - Support for bbox, convex hull, temporal extent, and placename geocoding
  - Interactive web UI at `/geoextent/` with file upload, remote extraction, and map preview
  - Comprehensive documentation and integration tests
- **Geoextent web interface** - Interactive tool at `/geoextent/` for extracting spatial/temporal extents from data files:
  - File upload with drag-and-drop support and size validation
  - Remote resource extraction via DOI/URL (comma-separated identifiers)
  - Interactive Leaflet map preview with clickable features showing properties
  - Parameter customization (bbox, tbox, convex hull, placename, gazetteer selection)
  - Response format selection (GeoJSON, WKT, WKB)
  - Download results in selected format
  - Documentation section with supported formats and providers
  - Added to main menu and sitemaps
- **Feeds sitemap** - Dynamic `/sitemap-feeds.xml` listing all regional feeds (continents and oceans) for search engine discovery
- **Wikidata export** - Export publication metadata to Wikibase/Wikidata instances:
  - Export works with spatial metadata to Wikidata
  - Support for complex geometries (points, lines, polygons, multigeometry)
  - Export extreme points (northernmost, southernmost, easternmost, westernmost) and geometric center
  - Configurable via `WIKIBASE_*` environment variables
- **Geocoding/gazetteer search** - Map search functionality allowing users to search for locations by name:
  - Nominatim geocoder integration (default)
  - Optional GeoNames support (requires username configuration)
  - Search results displayed on map with zoom to location
  - Accessible via search box in map interface
- **Works list with pagination** - Browse all works page at `/works/list/` with:
  - Configurable pagination (default 50 items per page)
  - User-selectable page size with min/max limits
  - Cached publication statistics (total works, published works, metadata completeness)
  - Direct links to work landing pages
- **Regional subscription system** - Users can subscribe to receive notifications for new publications from specific continents and oceans. Features include:
  - Checkbox-based UI with 8 continents and 7 oceans
  - "All Regions" checkbox to select/deselect all at once
  - "Disable all" link for quick clearing
  - Real-time subscription summary showing currently monitored regions
  - Persistent subscriptions across login sessions
  - Comprehensive test coverage (16 tests)
- **Temporal extent contribution** - Users can now contribute temporal extent (start/end dates) in addition to spatial extent. Works can be published with either spatial, temporal, or both extents. Supports flexible date formats: YYYY, YYYY-MM, YYYY-MM-DD.
- **Complete status workflow documentation** - Documented all 6 publication statuses (Draft, Harvested, Contributed, Published, Testing, Withdrawn) with workflow transitions and visibility rules in README.md.
- **Burger menu navigation** - Added top bar hamburger menu (☰) next to user icon with dropdown links to all main pages including Home, Browse Works, Contribute, Data & API, Feeds, About, Contact, Accessibility, and GitHub code repository.
- **Human-readable sitemap** - New `/pages` endpoint showing organized list of all pages with descriptions, categorized into Main Pages, Data & Technical, Information & Help, User Pages, and Development sections.
- **Custom error pages** - Added styled 404 and 500 error pages matching application design with navigation links and help information directing users to About and Accessibility pages.
- **Map popup enhancement** - Added "View Publication Details" button to map popups linking to work landing pages.
- **Paginated popup for overlapping features** - When multiple publications overlap on the map, a paginated popup allows users to cycle through them with Previous/Next navigation showing "Publication X of Y".
- **Point geometry highlighting** - Map markers (CircleMarkers) now show visual feedback when selected with increased size (10px) and high-contrast gold/orange colors, matching polygon highlighting behavior.
- **Admin unpublish functionality** - Admins can unpublish works, changing status from Published to Draft.
- **RSS/Atom feed harvesting support** - Added support for harvesting publications from RSS/Atom feeds in addition to OAI-PMH.
- **Django management command `harvest_journals`** - Command-line tool for harvesting from real journal sources with progress reporting and statistics.
- **Comprehensive test coverage** - Added 40+ new tests covering temporal contribution, status workflow, RSS harvesting, error handling, and real journal harvesting.

### Changed

- **Contribution page pagination** - Added full pagination support to the contribution page (`/contribute/`) with:
  - Configurable page size (default 50, min 10, max 200 works per page)
  - User-selectable page size dropdown with automatic form submission
  - Full pagination controls at top and bottom (First, Previous, page numbers, Next, Last)
  - Shows current range (e.g., "Showing 1 to 50 of 150 works")
  - Fixed variable name bugs (`publication` → `work` throughout template)
  - Reuses the same pagination layout as works listing page for consistency
- **Model terminology alignment** - Renamed base entity from "publications" to "works" throughout the codebase to align with [OpenAlex terminology](https://docs.openalex.org/api-entities/works):
  - Django app renamed from `publications/` to `works/`
  - `Publication` model renamed to `Work`
  - API endpoint changed from `/api/v1/publications/` to `/api/v1/works/`
  - Sitemap updated from `/sitemap-publications.xml` to `/sitemap-works.xml`
  - URL patterns updated from `/publication/<id>/` to `/work/<id>/`
  - All import statements, templates, and configuration files updated
  - Fresh migrations created from scratch
  - All test fixtures updated
- **Work type taxonomy** - Added comprehensive `type` field to works using Crossref/OpenAlex controlled vocabulary:
  - 39 work types supported (article, book, book-chapter, dataset, preprint, dissertation, etc.)
  - Type set from source's `default_work_type` during harvesting
  - Overridden by OpenAlex API type when available
  - Indexed and filterable in admin interface
- **Removed external CDN dependencies** - All JavaScript and CSS libraries now served locally for improved privacy, security, and offline functionality
- **Improved map accessibility** - Enhanced keyboard navigation and screen reader support for map interactions
- **Regional subscription email notifications** - Notification emails now group publications by region with dedicated sections for each subscribed continent or ocean. Each region section includes:
  - Region name and type (Continent/Ocean)
  - Count of new publications in that region
  - Direct link to the region's landing page to view all publications
  - Up to 10 publications per region in email (with link to view more)
  - Subject line shows total publication count across all regions
- **Unified contribution workflow** - Single "Submit contribution" button for both spatial and temporal extent. Users can submit either or both in one action.
- **Unified admin control panel** - Consolidated admin status display, publish/unpublish buttons, provenance information, and "Edit in Admin" link into single highlighted box at top of work landing page. Provenance is collapsible.
- **Improved text wrapping** - Page titles and abstract text now properly wrap on narrow windows instead of overflowing.
- **Unified URL structure** - Changed ID-based URLs from `/publication/<id>/` to `/work/<id>/` for consistency with DOI-based URLs.
- **Refactored views_geometry.py** - Eliminated code duplication by making DOI-based functions wrap ID-based functions. Reduced from 375 to 240 lines (~36% reduction).
- **Renamed "Locate" to "Contribute"** - URL, page title, and navigation updated for clarity about crowdsourcing purpose.
- **Contribute page layout refactored** - Fixed text overflow issues with proper CSS containment strategy.
- **Flexible publishing requirements** - Harvested publications with geometry can be published directly without requiring user contribution.
- **Contribute page login button improved** - Changed to informational disabled button with clear text: "Please log in to contribute (user menu at top right)".
- **Simplified footer navigation** - Footer now contains only Sitemap, About/Contact/Imprint, Privacy, and data license. Other page links moved to burger menu and sitemap.

### Fixed

- **JavaScript scope error** - Fixed "drawnItems is not defined" error in contribution form by declaring variable in outer scope.
- **GeoJSON geometry detection** - Fixed map click detection for GeoJSON layers by working directly with `layer.feature.geometry` instead of unreliable `instanceof` checks. Implemented proper point-in-polygon (ray casting), point-on-line (distance threshold), and point detection algorithms.
- **Map popup null location error** - Fixed crash when opening paginated popup by reordering operations to close existing popup before setting new location.
- **Highlight persistence after popup close** - Geometries now properly return to default blue style when popups close, removing gold dashed borders and explicit fill colors.
- **Individual popups during pagination** - Individual feature popups no longer open simultaneously with paginated popup, preventing UI conflicts.
- **Close button highlight clearing** - Popup close button (X) and ESC key now properly clear geometry highlights, not just map clicks.
- **First page highlight race condition** - Fixed race condition where first page of paginated popup wasn't highlighted due to premature clearing by `popupclose` event handler.
- **CircleMarker style properties** - Point geometries now use appropriate style properties (`radius` instead of `dashArray`) for proper visual feedback.
