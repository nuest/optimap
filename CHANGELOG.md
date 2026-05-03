# Changelog

All notable changes to OPTIMAP are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed

- **`Source.save()` no longer queues every source to fire immediately, and no longer resets the schedule on unrelated edits.** `Schedule.next_run` defaults to `timezone.now`, so the previous "delete-and-recreate on every save" path produced two surprising symptoms: (1) bulk-creating sources via `harvest_journals --insert-sources` (or any seed script) caused every source's recurring schedule to fire on the next Q-cluster tick — so triggering one source from the admin would visibly run a *different* source first; (2) editing any unrelated field on a `Source` reset its `next_run` to "now", causing unintended immediate harvests. `save()` now sets the freshly-created schedule's `next_run` to `now() + harvest_interval_minutes`, and preserves the existing schedule row (no delete/recreate, no `next_run` reset) when the interval is unchanged. Existing deployments may want to either inspect `/admin/django_q/schedule/` for stale `next_run=now` rows or just let the next harvest cycle re-stabilise them.

### Changed

- **HTTP `Referrer-Policy` is now `strict-origin-when-cross-origin`** so the OpenStreetMap tile server stops blocking our map requests. Django's `SecurityMiddleware` was relying on its built-in `"same-origin"` default, which strips the `Referer` on cross-origin requests — and OSM's [tile-usage policy](https://wiki.openstreetmap.org/wiki/Referer) explicitly rejects clients that send no `Referer`. The new value sends only the origin (no URL path) on third-party requests, satisfies OSM's identification requirement, and matches modern browser defaults.

- **OAI-PMH harvester is now hardened against transient and content-type errors.** `harvest_oai_endpoint` uses a `requests.Session` with retries (3 attempts, exponential back-off, on 429/500/502/503/504 and connection/timeout errors), a 30-second timeout, and an `OPTIMAP-harvester/1.0` User-Agent. The response is now sniffed before being passed to the XML parser — non-XML 200 responses (e.g. an HTML maintenance page) are rejected with a body preview in the error log, so operators can diagnose upstream changes without spelunking. The two live-endpoint tests against Copernicus (`test_real_journal_harvesting_essd` / `_geo_leo`) now skip cleanly when the upstream is unreachable.

### Added

- **`reset_harvest_schedules` management command** — rebuilds every `Harvest Source <id>` recurring Django-Q schedule with a properly deferred `next_run`, staggered across the smallest harvest interval so the cluster does not get a thundering herd. Companion to the `Source.save()` fix above for recovering existing deployments whose Schedule rows already have `next_run=now`. Flags: `--dry-run`, `--no-stagger`, `--clear-manual` (also wipes leftover `Manual Harvest Source <id>` one-offs from the admin "Schedule harvesting" action).

- **`harvest_journals --insert-sources`** — bulk-creates `Source` rows for every (enabled) entry in the command's `SOURCE_CONFIG` without harvesting, so the configured journal sources show up in the Django admin and can be triggered from there. Existing rows (matched by name or URL) are left untouched. Disabled journals are skipped unless `--include-disabled` is also given. Warns when an inserted source is not OAI-PMH (RSS / Crossref-prefix), since the auto-schedule and admin trigger both call `works.tasks.harvest_oai_endpoint` and won't dispatch correctly for those — they still need the CLI route until the dispatch logic is generalised.

- **Admin UI for harvesting management and log exploration** (issue #228) — `Source` is now registered in the Django admin (`/admin/works/source/`) with list, filter, search, and three bound actions ("Trigger harvesting for selected sources", "Trigger harvesting for all sources", "Schedule harvesting"). The trigger actions now enqueue via Django-Q `async_task` instead of running synchronously in the request thread (which hit gunicorn worker timeouts on non-trivial sources). `HarvestingEvent` now persists the harvested-record counts (`records_added`, `records_with_spatial`, `records_with_temporal`), the `error_message` on failure, and the full per-event `log_text` summary captured by `HarvestWarningCollector`. The `HarvestingEventAdmin` change form renders these as readonly fields with a `<pre>`-formatted log block (mirroring `WikidataExportLogAdmin`), exposes `date_hierarchy` + full-text search across `log_text`/`error_message`, links each event back to its `Source`, blocks manual `add` (events are machine-created), and offers a "Retry selected harvesting events" action. Each `Source` change page also shows the five most recent events inline. Fixes a latent bug where the scheduled harvest used the stale dotted path `'publications.tasks.harvest_oai_endpoint'` instead of `'works.tasks.harvest_oai_endpoint'`.

- **Profanity filter on Recognition Board usernames** — submitted display names are checked against [`better-profanity`](https://pypi.org/project/better-profanity/)'s default English word list (split on `-`/`_` so slug-style names are checked word-by-word). Offensive names are rejected with a generic "please choose a different username" message; the auto-generated `coolname` defaults are also re-checked, so users never receive a flagged suggestion. Best-effort: profanity filters always have false positives, so admins can adjust manually if needed.

- **Flash messages are now visible on every page.** Django's `messages` framework was wired up in views (e.g. on Recognition Board form errors) but no template rendered them, so users only saw a redirect with no on-screen explanation. `base.html` now renders queued messages as dismissible Bootstrap alerts above the page content, with `error`-level messages mapped to `alert-danger` and the rest to their matching alert class.

- **Contributor Recognition Board** (issue #240) — new public `/recognition-board/` page recognising users who add spatial or temporal metadata to OPTIMAP works. Contributions are now tracked per event in a structured `Contribution` model in addition to the existing free-text `Work.provenance` log; counts are always recorded regardless of opt-in. Users opt in and choose a display name (auto-filled with a `coolname`-generated slug) under Settings → Recognition Board. Contributors are grouped into five explorer-named tiers — Marco Polo, Vasco da Gama, Ferdinand Magellan, James Cook, Roald Amundsen — using a logarithmic scale (1, 10, 100, 1000, 10000 total contributions). Each tier title links to the explorer's Wikipedia page via a small info icon. Spatial and temporal contributions are shown separately in each tier with `fa-map-marked-alt` and `fa-clock` icons.

- **Minimal SEO surface on landing pages** (issue #22) — work landing pages now emit Open Graph, Twitter Card, schema.org `ScholarlyArticle` JSON-LD, and Google Scholar `citation_*` tags. The `ScholarlyArticle` JSON-LD includes `spatialCoverage` and `temporalCoverage` mirroring exactly what we *consume* from harvested Janeway pages, closing the loop. The homepage emits `WebSite` + `SearchAction`, and the regional feed pages emit `CollectionPage` JSON-LD with the region as the `about` `Place`. `<link rel="canonical">` is set on every page that ships SEO context. Built on `django-meta`.
- **Open Graph preview images for work landing pages** (issue #22) — a new `/work/<id>/preview.png` endpoint renders a 1200×630 PNG showing the work's spatial extent on an OSM basemap with a small "OPTIMAP" wordmark in the bottom-right. Served as `og:image` / `twitter:image`. Cached lazily on disk and invalidated by a `post_save` signal on `Work`. Works without geometry skip the `og:image` tag entirely.

- **`.zenodo.json` deposit metadata** (issue #16) — adds a Zenodo deposit metadata file at the repository root so that GitHub releases archived to Zenodo are populated with a curated title, description, creators, license, keywords, and links to related resources (KOMET/OPTIMETA project pages, the live instance, the GeoJSON/GeoPackage data downloads, the OpenAPI schema, and the OPTIMETA Geo OJS plugin).

<!-- REUSE-IgnoreStart -->
- **REUSE / SPDX license headers on all source files** (issue #30) — every first-party `.py`/`.js`/`.css`/`.html`/`.sh` file now carries a two-line SPDX header (`SPDX-FileCopyrightText` + `SPDX-License-Identifier: GPL-3.0-or-later`). A `REUSE.toml` covers migrations, fixtures, vendored static assets, and binaries. Run `reuse lint` to verify; the package is in `requirements-dev.txt`.
<!-- REUSE-IgnoreEnd -->
- **Janeway harvesting and `janeway_geometadata` plugin support** (issues #15, #18) — OAI-PMH harvesting now picks up geospatial and temporal metadata published by Janeway journals running the [`janeway_geometadata`](https://github.com/GeoinformationSystems/janeway_geometadata) plugin (e.g., DQJ, EarthArxiv, EcoEvoArxiv). The HTML extractor tries, in priority order:
  1. schema.org JSON-LD `spatialCoverage` / `temporalCoverage` (supports GeoJSON `geo`, schema.org `GeoShape` `box`, and `GeoCoordinates`),
  2. `<link rel="alternate" type="application/geo+json">` — fetched and merged when present,
  3. `DC.SpatialCoverage` GeoJSON `Feature`/`FeatureCollection`,
  4. `DC.box` (`name=…; northlimit=N; southlimit=S; westlimit=W; eastlimit=E; projection=EPSG4326`).
  The provenance log records which signal was used per work.
- **ISO 8601 open intervals** in `DC.temporal` / `DC.PeriodOfTime` and JSON-LD `temporalCoverage` are now parsed correctly: `../2024-12-31` produces `(None, "2024-12-31")` instead of storing `'..'` as a date string. Single instants (no `/`) are stored as `(value, value)`.
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
- **Global regions layer** - Interactive map overlay showing continent and ocean boundaries:
  - Toggle-able layer control to show/hide global regions on the main map
  - Simplified ocean geometries for efficient rendering
  - Color-coded regions (brown for continents, blue for oceans)
  - Dashed line styling for clear visual distinction
  - Click to view region details and navigate to regional feeds
  - Integrated with feed landing pages showing region outlines
- **Zoom-to-all features control** - Quick navigation button on all maps:
  - Expands view to fit all publications in the current context
  - Available on main map, feed landing pages, and work landing pages
  - Accessible button with screen reader support
  - Uses FontAwesome expand icon for visual clarity
- **Geocoding/gazetteer search** - Map search functionality allowing users to search for locations by name:
  - Nominatim geocoder integration (default)
  - Optional GeoNames support (requires username configuration)
  - Search results displayed on map with zoom to location
  - Accessible via search box in map interface
  - Available on feed landing pages and work landing pages for consistent navigation
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
- **Consolidated work identifier logic** - Centralized logic for determining work identifiers (DOI or internal ID) in a `get_identifier()` method on the `Work` model:
  - Ensures consistent identifier usage across permalinks, sitemaps, and API responses
  - Prioritizes DOI when available, falls back to internal ID
  - Reduces code duplication across views and serializers
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
