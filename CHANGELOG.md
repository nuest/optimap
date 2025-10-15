# Changelog

## [Unreleased]

### Added

- **Temporal extent contribution** - Users can now contribute temporal extent (start/end dates) in addition to spatial extent. Works can be published with either spatial, temporal, or both extents. Supports flexible date formats: YYYY, YYYY-MM, YYYY-MM-DD.
- **Complete status workflow documentation** - Documented all 6 publication statuses (Draft, Harvested, Contributed, Published, Testing, Withdrawn) with workflow transitions and visibility rules in README.md.
- **Map popup enhancement** - Added "View Publication Details" button to map popups linking to work landing pages.
- **Admin unpublish functionality** - Admins can unpublish works, changing status from Published to Draft.
- **RSS/Atom feed harvesting support** - Added support for harvesting publications from RSS/Atom feeds in addition to OAI-PMH.
- **Django management command `harvest_journals`** - Command-line tool for harvesting from real journal sources with progress reporting and statistics.
- **Comprehensive test coverage** - Added 40+ new tests covering temporal contribution, status workflow, RSS harvesting, error handling, and real journal harvesting.

### Changed

- **Unified contribution workflow** - Single "Submit contribution" button for both spatial and temporal extent. Users can submit either or both in one action.
- **Unified admin control panel** - Consolidated admin status display, publish/unpublish buttons, and "Edit in Admin" link into single highlighted box at top of work landing page.
- **Improved text wrapping** - Page titles and abstract text now properly wrap on narrow windows instead of overflowing.
- **Unified URL structure** - Changed ID-based URLs from `/publication/<id>/` to `/work/<id>/` for consistency with DOI-based URLs.
- **Refactored views_geometry.py** - Eliminated code duplication by making DOI-based functions wrap ID-based functions. Reduced from 375 to 240 lines (~36% reduction).
- **Renamed "Locate" to "Contribute"** - URL, page title, and navigation updated for clarity about crowdsourcing purpose.
- **Contribute page layout refactored** - Fixed text overflow issues with proper CSS containment strategy.
- **Flexible publishing requirements** - Harvested publications with geometry can be published directly without requiring user contribution.
- **Contribute page login button improved** - Changed to informational disabled button with clear text: "Please log in to contribute (user menu at top right)".

### Fixed

- **JavaScript scope error** - Fixed "drawnItems is not defined" error in contribution form by declaring variable in outer scope.
