# Changelog

## [Unreleased]

### Added

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
