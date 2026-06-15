# Changelog

All notable changes to OPTIMAP are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- **Collection logo** (closes #258): admins and curators can set an external logo URL on a collection. The logo is displayed as a thumbnail on the collection landing page (in the metadata line) and on the `/collections/` index cards. The field is also exposed via the REST API (`/api/v1/collections/`). Curators can set, update, or clear the logo via an inline edit form on the collection page — no file upload, external URL only.

### Fixed

- **Fix EarthArXiv OAI-PMH harvesting timeout**: the harvester now splits every harvest into per-calendar-year requests (`from`/`until`), starting with the most recent year and working backwards, so no single request asks the server for its full record history. Empty year ranges return `noRecordsMatch` and are skipped gracefully; existing records are skipped by the normal dedup logic. Sources whose stored URL already contains explicit `from=`/`until=` params are left unchanged (no chunking). The per-request timeout is also raised from 30 s to 90 s (configurable via `OPTIMAP_OAI_HTTP_TIMEOUT`).

- **Fix UI tests** (closes #142): remove module-level code in `test_loginconfirm.py` that crashed test discovery; remove stale `@unittest.skip` and duplicate nested class from `test_article_landing.py` and move it to `tests/` (the URL it targets has been implemented); fix three stale assertions broken by prior renames (feeds→regions, BoK URL, login response wording).

### Changed

- **Accessibility improvements across all pages** (closes #173). Template-level WCAG 2.1 fixes: `role="application"` and `aria-label` added statically to map containers (`<div id="map">`, `<div id="mini-map">`); `aria-modal="true"` and `aria-labelledby` added to both account-deletion modals in user settings; missing `<label for="email_new">` added to the change-email form; grouped region checkboxes on the subscriptions page now use semantic `<fieldset>`/`<legend>` instead of `<div>`; all data tables on the statistics page now have `scope="col"` on `<th>` elements; Chart.js canvas elements have `aria-label` and a visible text caption; decorative icons inside badges now carry `aria-hidden="true"`; dropdown dividers in the navigation menu are marked `aria-hidden="true"`; the generic "here" link in the About page is replaced with descriptive anchor text; the "accessibility" typo in about.html is fixed. Automated testing: `axe-selenium-python` added to dev dependencies; new `tests-ui/test_accessibility.py` runs axe-core scans on six public pages asserting zero critical/serious violations; new `tests/test_accessibility_html.py` adds fast Django-client assertions for the specific ARIA attributes introduced.

## [0.25.0] - 2026-06-12

### Added

- Add Ruff code formatter with enforcement via test suite and CI (#70). Configuration in `pyproject.toml` (line length 119, rules E/F/I). VSCode format-on-save via `.vscode/settings.json`; PyCharm via the Ruff plugin.

### Changed

- **EO4GEO BoK upgraded to `current` version (GeoSpaceBoK, 1,212 concepts)**. The default `OPTIMAP_BOK_VERSION` is now `current` instead of the pinned `v3` snapshot. The `current` version is served by [geospacebok.eu](https://geospacebok.eu) and adds 327 concepts compared to v3, including a heavily expanded GC3 AI/ML hierarchy (6 → 52 codes, e.g. `GC3-11-2` Space-time dynamic reasoning) and a new top-level `GN` category for GNSS concepts (~277 sub-codes). `OPTIMAP_BOK_CONCEPT_BASE_URL` default updated from `http://bok.eo4geo.eu` to `https://geospacebok.eu`; concept chips now link to `https://geospacebok.eu/<CODE>`. The `--version` flag on `refresh_bok_snapshot` has been renamed to `--bok-version` to avoid conflict with Django's built-in `--version` flag.

- **Richer `GET /api/v1/sources/` and `GET /api/v1/sources/<id>/` responses** (partial #247). Each source now includes `source_type`, `source_type_display`, `homepage_url`, `abbreviated_title`, `is_oa`, `is_preprint`, `source_url` (absolute API self-link), and `collection` (identifier + name + API URL of the default collection, or `null`). The endpoint is now `AllowAny` (was `IsAuthenticatedOrReadOnly` — the data was already public). The embedded `source_details` block in Work API responses is updated to match.

- **Global data dumps (GeoJSON / GeoPackage / CSV) now include meaningful source and collection references** (partial #247). The raw integer `source` FK has been replaced with `source_name` (human-readable name) and `source_url` (absolute API endpoint for the source). A new `collections` field lists the collection identifiers each work belongs to. Internal fields that are meaningless to data consumers — `job`, `created_by`, `updated_by`, `status`, `creationDate`, `lastUpdate`, `provenance`, `openalex_match_info`, `openalex_fulltext_origin`, `openalex_ids` — have been removed from the dump. GeoPackage and CSV are derived from the improved GeoJSON via `ogr2ogr` and pick up these changes automatically. **This is a breaking change** for existing consumers that rely on the removed columns or on `source` being an integer.

- **All outgoing emails now use file-based Django templates** (closes #110). Email bodies and subjects are stored in `works/templates/email/*.en.txt` — one file per email type (12 templates total). Subject lines are on the first line of each template; a blank line separates them from the body. Every subject now carries a `[OPTIMAP]` prefix and a relevant emoji. Autoescape is disabled for plain-text output so URLs are never HTML-encoded. Future language variants drop in as `*.de.txt` etc. with no code changes required. Missing content assertions for the magic-link, email-change, and account-deletion emails were added as part of this change.

- **Login, logout, and email-change flows now redirect to `/` with a flash message** instead of rendering dedicated single-alert pages. Removed `login_response.html`, `logout.html`, `changeuser.html`, and dead `deleteaccount.html` templates; removed corresponding dead `delete_account` view. Login and email-change messages use `extra_tags="persist"` so they stay visible until manually dismissed.
- **Per-message auto-close TTL for flash alerts.** Pass `extra_tags="persist"` to any `messages.*()` call to suppress auto-close entirely; `error` and `warning` level messages default to 8 s, `info`/`success` to 5 s (previously all server-rendered alerts shared a single 5 s timeout). `OPTIMAP_FLASH` JS alerts for `warning` now also get 8 s to match. The Bootstrap level tag (`alert-danger` etc.) is now derived from `message.level_tag` rather than the combined `message.tags` string, so `extra_tags` values no longer bleed into the CSS class.
- **Client-side geometry simplification for oversized polygons.** When an NER/gazetteer-suggested polygon exceeds the configurable warn threshold (default 50 KB), a simplification panel appears below the map instead of silently failing. The panel shows a logarithmic tolerance slider (0.01°–1°, covering ~1–111 km) with before/after point-count and size stats and a live Leaflet preview that updates as the slider moves. Three preset buttons (Light ~1 km / Medium ~11 km / Aggressive ~55 km) snap the slider to common values. At submit time, payloads above the hard limit (default 2 MB) are blocked and the panel is shown again. Both thresholds are server-configurable via `OPTIMAP_GEOMETRY_WARN_SIZE_KB` and `OPTIMAP_GEOMETRY_MAX_UPLOAD_KB`. Simplification uses Leaflet's built-in `L.LineUtil.simplify()` (Ramer–Douglas–Peucker) with no additional JS dependency.

### Added

- **Configurable notification intervals for regional subscriptions** (closes #85). Users can now choose between **weekly** (every Monday) and **monthly** (last day of month) email notifications on the subscriptions page. The selected interval is stored per subscription; existing subscribers default to monthly. Notifications now only include works published since the last successful notification, fixing a bug where the same papers were re-sent on every run.

- **Georeferencing game** (closes #14). A "Play" button in the top navbar and the burger menu sends users to `/contribute/next/`, which picks a random work still needing geolocation and redirects to its landing page in game mode. After each contribution, the page auto-advances to the next challenge instead of reloading. A game banner shows how many works have been georeferenced in the current session, with a "Skip to next" button. The NER location-suggestion panel opens and runs automatically in game mode so place suggestions are ready immediately. Game can be scoped to a single collection via `?collection=<identifier>`. A "Play georeferencing game" button also appears on `/contribute/` (and collection-filtered variants). Contributions made through the game are marked `game: true` in the work's provenance event log. A **"Play" button** is now shown next to the "Contribute metadata" button on collection landing pages, starting the georeferencing game scoped to that collection.

- **Chunked map loading with lazy popup details** (closes #256). The main map now loads works in configurable pages (default 1 000, `OPTIMAP_MAP_CHUNK_SIZE`) instead of one ~9 MB request; each chunk is rendered immediately so markers appear progressively. Initial chunks carry only geometry and minimal metadata (id, title, doi, status) via `?minimal=true`; full work details (abstract, source, OpenAlex fields) are fetched once from `GET /api/v1/works/<id>/` the first time a popup is opened and cached for the session. A loading indicator shows progress (`Loading works… N / M`). Both the single-feature popup and the paginated overlapping-works popup share the same lazy-load mechanism.

- **Link headers on paginated API responses** (RFC 5988). All paginated endpoints (`/api/v1/works/`, `/api/v1/sources/`, etc.) now emit a `Link:` response header with `rel="next"`, `rel="prev"`, `rel="first"`, and `rel="last"` URLs, following the same convention as the GitHub REST API.

- **`GET /api/v1/statistics/` — cached aggregate counts** (partial #160). Returns `published_works`, `total_works`, `total_works_for_user` (auth-aware: `published_works` for anonymous/non-staff, `total_works` for staff — matches what `/api/v1/works/` returns for the caller), `works_by_status` (per status code), `with_geometry`, `with_temporal`, `with_complete_metadata`, `complete_percentage`, `sources`, `collections`, `users`. Cached for 24 h. No authentication required; `works_by_status` is always included so harvested-work counts are public.

- **GeoScienceWorld as a new harvesting source type** (closes #251). A new `geoscienceworld` source type enumerates articles from Crossref by DOI prefix and extracts geographic coordinates from each article's GSW landing page via geoextent's built-in GeoScienceWorld content provider (which handles Cloudflare via `curl_cffi`). Three initial source configs are provided in `harvest_sources.py`: SEG (prefix `10.1190`), Geological Society of London (`10.1144`), and Mineralogical Society (`10.1180`). The `Source` model gains a new `doi_prefix` field used by both `crossref-prefix` and `geoscienceworld` harvesters, replacing the hardcoded `10.5194` Copernicus fallback in the Crossref harvester. Temporal/epoch extraction from GeoRef metadata is deferred pending [nuest/geoextent#122](https://github.com/nuest/geoextent/issues/122); tracked in #257.

- **Pagination on collection detail pages** (`/collections/<slug>/`). Collections with more than `OPTIMAP_PAGE_MAX_ITEMS` works (default 50) now show paginated work cards with configurable page size and first/prev/next/last navigation, replacing the previous hard cap of 100 with a static "showing first N" alert. A "Show only page on map" / "Show all on map" toggle button appears above the map; choosing "show all" fetches the full collection GeoJSON once and caches it in `sessionStorage` so subsequent page navigations are instant. Introduces a new `OPTIMAP_PAGE_MAX_ITEMS` setting (default 50) used by all paginated list views; the previous `OPTIMAP_WORKS_PAGE_SIZE_DEFAULT` remains as a fallback for backward compatibility. Pagination nav markup and the page-size dropdown are now shared via `_pagination.html` / `_pagination_nav.html` template includes, replacing duplicated blocks in `works.html` and `contribute.html`; the default page size (50) is now always present as a selectable option.

- **NER-based location suggestions on the work contribution form** (closes #199). A collapsible "Suggest locations from text" panel on the work landing page runs spaCy Named Entity Recognition on the work's title and abstract (two parallel API calls), looks up found place names via a configurable gazetteer (Nominatim by default), and presents the results as a selectable list. Matched spans are highlighted in the text preview using character offsets. Each place can be added to the Leaflet map individually or via "Add all to map". New REST endpoint: `POST /api/v1/geoextent/extract-text/` (see `docs/ner_location_suggestions.md`). Provenance events record `geometry_source` when NER-derived geometry is contributed. spaCy model auto-downloads on first use (~12 MB). Requires `geoextent>=0.13.0`.

- **REST API for collections at `/api/v1/collections/`**. `GET /api/v1/collections/` lists all published collections (paginated); `GET /api/v1/collections/<identifier>/` retrieves a single collection by its slug. Each response includes `works_count` (published works only), `collection_url`, and embedded `feeds` and `downloads` link objects. Staff can additionally retrieve unpublished collections. Documented in the OpenAPI schema under the *Collections* tag.

### Fixed

- **Privacy-policy consent is now explicitly recorded.** `UserProfile` gains a `consented_at` timestamp (nullable; `null` for accounts created before this change) that is stamped when a user clicks "I consent" on their first magic-link login. Previously consent was only implicit (account existence). A companion fix to `works/signals.py` makes the `UserProfile` auto-creation signal safe for legacy / admin-created accounts that have no profile row yet (`get_or_create` instead of a bare `instance.userprofile.save()` that would raise `RelatedObjectDoesNotExist`).

- **GeoJSON and GeoPackage downloads no longer emit bare `GeometryCollection` wrappers.** Django's `GeometryCollectionField` always serializes geometries as `GEOMETRYCOLLECTION(…)`, even for single primitive shapes. This caused GeoPackage layers to be declared as `GEOMETRYCOLLECTION`, which QGIS and other GIS tools cannot render with default symbology (layers appeared empty). The fix applies to every download endpoint: collection GeoJSON/GeoPackage (`/api/v1/collections/<slug>/download/{geojson,gpkg}/`), global GeoJSON (`/download/geojson/`), and global GeoPackage (`/download/geopackage/`). Single-member collections are unwrapped to the primitive type (`Point`, `Polygon`, etc.); same-type multi-member collections are promoted to `Multi*`; mixed-type collections are left as-is. GDAL format validation tests were added for all affected endpoints.

- **GeoRSS and Atom feeds for individual collections** (closes #248). Each published collection now has a GeoRSS feed at `/api/v1/feeds/collection-<slug>.rss` and an Atom feed at `/api/v1/feeds/collection-<slug>.atom`. Feed autodiscovery `<link>` tags are injected into the collection detail page `<head>`, and visible feed links appear in a new "Feeds & downloads" card on the page. Both URLs are listed in `sitemap-collection-feeds.xml`.

- **GeoJSON, GeoPackage, and CSV download endpoints for individual collections** (closes #217). Published collection works are downloadable at `/api/v1/collections/<slug>/download/geojson/`, `/gpkg/`, and `/csv/`. Results are cached for `FEED_CACHE_HOURS` (default 24 h); pass `?now` to force refresh. Download links appear in the new "Feeds & downloads" card on each collection page. All three endpoints are documented in the OpenAPI schema under the new *Collections* tag and indexed in `sitemap-collection-downloads.xml`.

- **31 additional Pensoft/ARPHA journals added as OAI-PMH sources.** All confirmed to embed `schema:contentLocation` GeoCoordinates JSON-LD (study-site points) in article pages. New source keys: `pensoft-zookeys`, `pensoft-phytokeys`, `pensoft-neobiota`, `pensoft-mycokeys`, `pensoft-herpetozoa`, `pensoft-natureconservation`, `pensoft-jhr`, `pensoft-alpineentomology`, `pensoft-subtbiol`, `pensoft-zse`, `pensoft-jor`, `pensoft-africaninvertebrates`, `pensoft-oneecosystem`, `pensoft-evolsyst`, `pensoft-dez`, `pensoft-mbmg`, `pensoft-neotropical`, `pensoft-zoologia`, `pensoft-biorisk`, `pensoft-caucasiana`, `pensoft-italianbotanist`, `pensoft-nl`, `pensoft-zitteliana`, `pensoft-abs`, `pensoft-saddi`, `pensoft-vdj`, `pensoft-anhmw`, `pensoft-aer`, `biosystecol`, `bulletinofinsectology`, `pensoft-nhcm`. Audit covered all 130 ARPHA OAI sets.
- **Biodiversity Data Journal (BDJ) added as an OAI-PMH source** (`pensoft-bdj`, closes #92). Harvest with `python manage.py harvest_sources --source pensoft-bdj`. The ARPHA OAI-PMH endpoint is filtered to the `bdj` set so only BDJ records are fetched.
- **`extract_geometry_from_html()` now extracts `schema:contentLocation` GeoCoordinates from JSON-LD** (closes #92). Pensoft/ARPHA journals embed study-site coordinates via `contentLocation` rather than `spatialCoverage`; the new extraction step sits between `spatialCoverage` and the `geo+json` link in the priority chain and collects all points into a single `GeometryCollection`.

- **OGC API - Features endpoint at `/ogcapi/`** (closes #19). Published works are now accessible via a standards-compliant [OGC API - Features](https://ogcapi.ogc.org/features/) interface powered by [pygeoapi](https://pygeoapi.io/) and its PostgreSQL/PostGIS provider. Supports `bbox`, `datetime`, and `limit`/`offset` query parameters. Returns proper GeoJSON FeatureCollections with `numberMatched` / `numberReturned` / pagination links. Only published works (`status='p'`) are served, via a dedicated `works_published` database view. Configuration in `etc/pygeoapi-config.yml`; generate the required OpenAPI document with `python manage.py generate_pygeoapi_openapi`. Client demo code for Python (`requests` + `geopandas` + `folium`), R (`sf` + `mapview`), and QGIS (GUI and PyQGIS console) in `docs/ogcapi-clients.md`.

- **Weekly inactivity warning email to users** (closes #120). Users who have not logged in for 12–13 months receive a warning that their account will be deleted if they do not log in within 30 days. The email explains what happens to their data (credentials removed; contributions remain but become anonymous; recognition board entry removed). Scheduled automatically via Django-Q every Monday.

- **Weekly deletion list for admins** (closes #121). Users inactive for over 13 months are reported in a weekly email to all staff users with an email address. The list includes each user's email, last-login date, and join date, with a link to the Django admin. If no users are pending deletion, no email is sent.

- **Sentinel "Deleted User" account for de-identified contributions.** When any user account is deleted, their contributions (spatial/temporal/ontology metadata on publications) are reassigned to a permanent `username="deleted"` sentinel account rather than set to `NULL`. This preserves contributed metadata in the admin UI with a clear "Deleted User" label instead of a blank. The sentinel is created automatically on each `migrate` run via a `post_migrate` signal and is accessible via `CustomUser.deleted_user()`. A `pre_delete` signal on `CustomUser` handles the reassignment for both user-initiated and admin-initiated deletions.

- **Inline curator management on collection pages** (closes #234). Admins and existing curators can add curators by email address and remove them directly from the collection landing page. When the curator list changes, all current curators, all admins, the actor, and the added/removed curator receive a notification email. The former Django Admin "Manage curators" link has been replaced by this in-page UI.

- **Admin notification on new user registration.** When a brand-new account is persisted (i.e. a magic-link recipient completes the second "confirm" step of the new-account flow), every `is_staff` user with an email address receives a notification with the new user's email and a link to the admin user page. Sent asynchronously via Django-Q and logged in `EmailLog` (`trigger_source="scheduled"`). The send failure path never blocks login.
- **Automatic BoK concept extraction from AGILE GISS PDFs** (closes #250). The Crossref harvester downloads the full-text PDF for each newly ingested AGILE GIScience Series paper and parses the "BoK Concepts" section. Three section formats are handled: bracketed codes (`[TA12-6]`), arrow-separated names (`concept → sub-concept`), and comma/semicolon-separated names. Extracted codes are validated against the cached BoK snapshot and stored in `Work.bok_concepts`; status stays `h` (machine action, not a human contribution). Provenance carries a `bok_pdf_extract` event recording the PDF URL and codes found. A new `python manage.py extract_agile_bok [--limit N] [--throttle SECONDS] [--force] [--dry-run]` command backfills the already-harvested corpus. The `agile-giss-openalex` predefined source is removed in favour of the authoritative Crossref route.

- **Tag works with EO4GEO Body of Knowledge concepts** (closes #245). New `bok_concepts` field on `Work` plus an autosuggest combobox on the work landing page (≥3-character query, full keyboard, multi-select) backed by `GET /api/v1/bok/search/`. Tagged concepts render as chips that link to the canonical concept page on [geospacebok.eu](https://geospacebok.eu), surface in the public Work API as `bok_concepts` / `bok_concepts_resolved`, and emit JSON-LD `about: [DefinedTerm,…]` on the landing page. Adding the first concept on a harvested work flips its status from Harvested to Contributed for admin review; Recognition Board credit is recorded under a new generic *Ontology contributions* kind (so the same bucket can later cover other controlled vocabularies) and deduped per (user, work) so the same user adding more concepts later does not double-count. The cached BoK snapshot is refreshed by `python manage.py refresh_bok_snapshot` (configurable via `OPTIMAP_BOK_VERSION`). The editor is **opt-in**: set `OPTIMAP_BOK_ENABLED_COLLECTIONS` to a comma-separated list of `Collection.identifier` slugs to enable it on works in those collections — empty (default) disables the editor site-wide. Read-only chips on already-tagged works remain visible regardless.

### Changed

- **Contribution editor open to logged-in users on both Harvested *and* Contributed works** so a second contributor can fill a different gap (e.g. add temporal extent after someone else added a geometry). Pre-existing extents no longer close the form: user B may replace user A's geometry, with the provenance log recording attribution.
- **Recognition Board credit dedupes per (user, work, kind) via the provenance log.** Re-editing the same property type on the same work counts once for that user; different users editing the same property each count separately. Applies to spatial, temporal, and the new ontology bucket.

- **Filter the contribute page by collection** with `/contribute/?collection=<identifier|id|short_slug>`; collection landing pages link into it.

- **Copy/paste geometries between the geoextent tool and the contribution form.** A new "Copy extents" button on `/geoextent/` saves all extracted geometries to the browser; a "Paste geoextents" button on the work landing page (when contributing spatial extent) pastes them into the map as editable layers ready to submit.

- **Admin-only "Publish all unpublished works" button on collection pages** — bulk-flips every Harvested or Contributed work in the collection to Published in one click. Curators see no button (admins-only). Draft / Testing / Withdrawn works are deliberately left untouched.

- **Mountain Wetlands and OpenAlex-as-source harvesters now auto-create a Collection** for the source on first run (mirroring the OAI-PMH path from issue #192). New collections start unpublished so admins can review name/description before exposing them on `/collections/`.

- **Separate "Unpublished works" map layer** for admins (main map) and collection curators (collection pages). Features split into two togglable layers, *Published works (N)* and *Unpublished works (N)* (dashed, muted). Popups for unpublished features show a status badge.

- **Publication status badge in all map popups.** Every popup (single-click and paginated) now shows a colour-coded status badge (green Published / teal Harvested / blue Contributed / etc.) in the header. Unpublished works also carry a "not visible to anonymous users" note. When paging through a cluster of overlapping geometries, the badge updates with each page so admins and curators can tell published from unpublished works at a glance.

- **Spatial and temporal extent indicators on work cards.** Collection pages (curators/admins), the Contribute listing, and the Works list now show green *Spatial* / *Temporal* badges on each work card when logged in — green if extent data is present, grey if absent — making data-completeness gaps visible at a glance without opening each work.

- **Point geometries on the main map now render as circle markers** (radius 6 px, same style as the work landing page) instead of the default Leaflet pin icons. Hover, click, and paginated-popup interaction all continue to work.

- **Work-state-change email notifications** — admins and collection curators receive an email when a user contributes spatial or temporal metadata; contributors receive an email when their work is later published. Per-user opt-out toggle on `/usersettings/`.

- **CSV download with WKT geometry column** (closes #206) — published works are exported as CSV at `/download/csv/` alongside GeoJSON and GeoPackage. New `python manage.py regenerate_data_dumps [--format geojson|gpkg|csv] [--dry-run]` command for synchronous on-demand regeneration.

- **Reverse-geocoded placename and country code on work landing pages**, with a tooltip noting Nominatim as the source. Per-point matches with permalinks to OSM are recorded under `Work.provenance.geocoding` for admins.

- **OpenAlex-as-source harvester** (`source_type='openalex'`) — uses OpenAlex itself as the harvest origin, configured with an OpenAlex Source identifier. New `python manage.py compare_agile_giss_routes` command diffs the OpenAlex and Crossref routes side-by-side.

- **Crossref harvester now extracts authors and biblio fields** (`volume`, `issue`, `first_page`, `last_page`).

- **Reverse-geocoded `placename` and `country_code` on the Work API** — both keys always emitted (null when absent).

- **Collection backlinks on work landing pages** — each work landing page lists the collections it belongs to; unpublished collections shown only to admins.

- **Inline curator-editable collection description** — curators (and admins) edit a collection's description directly on `/collections/<identifier>/`. Plain text only.

- **Admin-only "Manage curators" deep-link on the collection page** — one-click jump to the admin change form anchored on the curators field.

### Fixed

- **Returning users with mixed-case emails no longer see the consent screen or crash on login.** Email addresses are now normalised to lowercase at intake (`loginres`, `change_useremail`, `EmailChangeSerializer`) so the DB always stores lowercase values. The `?confirmed=true` branch uses `get_or_create` instead of `create_user` as a race-condition guard. Migration `0009` back-fills `LOWER()` on all existing `CustomUser.email`, `CustomUser.username`, and `BlockedEmail.email` rows; user lookups revert to exact `=` matches so the B-tree index is used again.

- **Admin "Trigger / Schedule / Retry harvesting" actions and `harvest_journals` now dispatch by `source_type`** instead of hardcoding the OAI task, so non-OAI sources (MaRESS, RSS, Crossref, OpenAlex) run the right harvester. `harvest_journals` also reconciles stale Source rows against `SOURCE_CONFIG` (rewrites `source_type`, fills blank soft fields, preserves admin edits).

- **Inline mutation buttons reflect the new state immediately on production.** Authenticated responses on `/collections/`, the work landing page, and `/subscriptions/` are no longer captured by the site-wide cache, so publish/unpublish/contribute/subscribe state flips on reload. Anonymous responses still cached.

- **"View work details" button now appears in single-feature popups for works without a DOI.**

- **Empty-DOI backfill on re-harvest** — works ingested without a DOI have it filled when a later harvest delivers one. `python manage.py backfill_openalex` also recovers DOIs via OpenAlex matches.

- **Collections entry restored to the burger menu**, and **collection-page work cards always link to the OPTIMAP landing page** rather than to an external URL.

### Changed

- **Mountain Wetlands harvester simplified now that MaRESS exposes DOIs** (closes #244). The harvester reads DOIs directly from the API (normalising `https://doi.org/…` → bare `10.x/y`). When the API already supplies both a DOI *and* authors, OpenAlex is skipped entirely — no extra metadata to recover and no wasted rate-limit budget. Records missing a DOI or authors fall back to the OpenAlex title+author path. `Work.provenance.openalex_match.status` gains a `skipped` value for the fast path.

- **`/collections/` work counts** show only published works to regular users; admins and curators of a collection get a per-status breakdown (zero-count rows hidden).

- **Data-dump regeneration unified into one umbrella task.** GeoJSON, GeoPackage, and CSV are produced from one intermediate. Retention now keeps the newest N timestamp groups rather than raw files.

- **HTML geotagging meta tags + spec-compliant schema.org `Place.geo` on work landing pages** (closes #222) — landing pages emit `geo.position`, `ICBM`, and (when available) `geo.placename` / `geo.region`. `ScholarlyArticle.spatialCoverage.geo` now follows [schema.org/geo](https://schema.org/geo): point geometries become `GeoCoordinates`, others become `GeoShape` with a `box`. Multi-point geometries reduced to the lowest common ancestor in the address hierarchy.

- **In-memory cache for hot anonymous reads** (closes #180, partially #7) — adds a `LocMemCache` alias for static / low-change anonymous pages (privacy, about, accessibility, feeds list, sitemap, robots.txt) and the work landing page. Responses advertise their TTL via `Cache-Control` and `Expires` headers. Authenticated/staff requests always render live.

- **Zotero / reference-manager metadata on work landing pages** (issue #243) — emits `citation_abstract` (full text), `citation_publisher`, `citation_language`, repeated `citation_keywords`, `citation_volume`/`issue`/`firstpage`/`lastpage`, and `citation_pdf_url`. Collection card pages also carry a COinS fallback for multi-item save.

- **Squashed Django migrations into a single `0001_initial`** in preparation for a clean redeployment.

### Added

- **`Work.placename` + `Work.country_code` populated by reverse geocoding** (issue #222). Gated by `OPTIMAP_GEOCODE_WORKS_ON_SAVE` (off by default). New `python manage.py backfill_placenames [--limit N] [--force] [--sleep 1.1] [--dry-run]` command.

- **OAI-PMH harvester auto-creates a Collection per endpoint** (closes #192) — the first harvest of an OAI/OJS/Janeway source creates a `Collection` and links it. New collections start `is_published=False`.

- **`HarvestingEvent.records_updated` counter** — every harvester tracks updated works separately from created ones, surfaced in the admin and the completion email.

- **Per-source dedup and careful-update flag in every harvester** — duplicate detection scoped to `Source`. New `--update` flag on `harvest_journals` (and `update_existing=True`) refreshes existing same-source works in place; user-contributed spatial/temporal metadata, `status`, and `created_by` are preserved.

- **Mountain Wetlands Repository harvester** (issue #192) — manual-only; run via `python manage.py harvest_journals --journal mountain-wetlands`.

- **Collections** (issue #192, foundation) — new `Collection` model groups works under a curated identifier. Routes: `/collections/`, `/collections/<identifier>/`. Curators add/remove works on the work landing page; admins publish/unpublish from either page. Includes a collection sitemap and burger-menu entry.

- **`Source.source_type` choice field** (`oai-pmh` / `ojs` / `janeway` / `rss` / `crossref-prefix` / `mountain-wetlands`) — replaces the implicit OAI-PMH assumption. Default `harvest_interval_minutes` flips to `0` (manual-only).

- **`Source.collection` foreign key** replaces the legacy `collection_name` string field.

- **Structured `Work.provenance` (JSONField)** with a defined schema (`harvest`, `metadata_sources`, `openalex_match`, `events`). User contributions and admin publish/unpublish actions append to `events`.

### Fixed

- **Crossref-prefix harvester no longer auto-publishes harvested works** — new works default to Harvested, not Published.

- **Work landing page hides the empty map when no geometry is available.** Shows a "no geospatial metadata" notice with a link to the contribution page instead.

- **`Source.save()` no longer queues every source to fire immediately, and no longer resets the schedule on unrelated edits.** New schedules use `now() + harvest_interval_minutes`; the schedule row is preserved when the interval is unchanged.

### Changed

- **Harvesting code split into the `works.harvesting` package** — one module per concern (OAI-PMH, RSS, Crossref, Mountain Wetlands, OpenAlex, sessions, helpers). Existing dotted-path imports (`works.tasks.harvest_*`) continue to resolve.

- **Database indices on hot `Work` query paths** (issue #141) — adds `status`, `(-creationDate, -id)`, `publicationDate`, and a partial `(-creationDate, -id) WHERE status='p'`.

- **HTTP `Referrer-Policy` is now `strict-origin-when-cross-origin`** so the OpenStreetMap tile server stops blocking map requests.

- **OAI-PMH harvester hardened against transient and content-type errors** — sessions get retries (3 attempts, exponential back-off), 30 s timeout, and a User-Agent. Non-XML 200 responses are rejected with a body preview.

### Added

- **`reset_harvest_schedules` management command** — rebuilds every `Harvest Source <id>` schedule with a deferred `next_run`, staggered. Flags: `--dry-run`, `--no-stagger`, `--clear-manual`.

- **`harvest_journals --insert-sources`** — bulk-creates `Source` rows for every entry in `SOURCE_CONFIG` without harvesting. `--include-disabled` opts in disabled journals.

- **Admin UI for harvesting management and log exploration** (issue #228) — `Source` is registered at `/admin/works/source/` with three actions ("Trigger harvesting", "Trigger harvesting for all", "Schedule harvesting"). `HarvestingEvent` admin shows record counts, error message, log block, and a "Retry" action; recent events appear inline on each `Source`.

- **Profanity filter on Recognition Board usernames** — submitted display names are checked against [`better-profanity`](https://pypi.org/project/better-profanity/)'s default list.

- **Flash messages are now visible on every page** — queued Django messages render as dismissible Bootstrap alerts in `base.html`.

- **Contributor Recognition Board** (issue #240) — public `/recognition-board/` page ranking users who contributed spatial or temporal metadata. Five explorer-named tiers (Marco Polo → Roald Amundsen) on a logarithmic scale (1 / 10 / 100 / 1000 / 10000). Opt-in display name set under Settings → Recognition Board.

- **Minimal SEO surface on landing pages** (issue #22) — work landing pages emit Open Graph, Twitter Card, schema.org `ScholarlyArticle` JSON-LD, and Google Scholar `citation_*` tags. Homepage emits `WebSite` + `SearchAction`; regional feeds emit `CollectionPage`. `<link rel="canonical">` on every SEO-relevant page.

- **Open Graph preview images for work landing pages** (issue #22) — `/work/<id>/preview.png` renders a 1200×630 PNG of the work's spatial extent on an OSM basemap. Disk-cached, invalidated on save.

- **`.zenodo.json` deposit metadata** (issue #16) — repository-root metadata file so GitHub releases archived to Zenodo are populated with title, description, creators, license, and links.

<!-- REUSE-IgnoreStart -->
- **REUSE / SPDX license headers on all source files** (issue #30) — every first-party file carries SPDX headers; `REUSE.toml` covers fixtures and vendored assets. Run `reuse lint` to verify.
<!-- REUSE-IgnoreEnd -->

- **Janeway harvesting and `janeway_geometadata` plugin support** (issues #15, #18) — OAI-PMH harvesting picks up geometries published by Janeway journals running [`janeway_geometadata`](https://github.com/GeoinformationSystems/janeway_geometadata). Extraction priority: schema.org JSON-LD → `<link rel="alternate" type="application/geo+json">` → `DC.SpatialCoverage` → `DC.box`.

- **ISO 8601 open intervals** in `DC.temporal` and JSON-LD `temporalCoverage` are parsed correctly: `../2024-12-31` produces `(None, "2024-12-31")`. Single instants stored as `(value, value)`.

- **Geoextent API** — REST endpoints exposing the [geoextent library](https://github.com/nuest/geoextent):
  - `/api/v1/geoextent/extract/` — extract from uploaded files (GeoJSON, GeoTIFF, Shapefile, GeoPackage, KML, CSV, etc.)
  - `/api/v1/geoextent/extract-remote/` — extract from remote repositories (Zenodo, PANGAEA, OSF, Figshare, Dryad, GFZ, Dataverse)
  - `/api/v1/geoextent/extract-batch/` — batch processing
  - Response formats: GeoJSON (default), WKT, WKB. Optional placename via Nominatim / GeoNames / Photon.

- **Geoextent web interface** — interactive tool at `/geoextent/` for file upload, remote extraction by DOI/URL, Leaflet preview, parameter customisation, and result download.

- **Feeds sitemap** — `/sitemap-feeds.xml` listing all regional feeds.

- **Wikidata export** — export work metadata to a Wikibase/Wikidata instance, including extreme points and geometric centre. Configured via `WIKIBASE_*` environment variables.

- **Global regions layer** — toggleable map overlay showing continent and ocean boundaries; click for region details and regional feed.

- **Zoom-to-all features control** — quick-fit button on every map.

- **Geocoding/gazetteer search** — search-by-location on map (Nominatim default; GeoNames optional).

- **Works list with pagination** — `/works/list/` browse page with configurable page size.

- **Regional subscription system** — subscribe to email notifications for new works in selected continents/oceans.

- **Temporal extent contribution** — users contribute temporal extent (start/end dates) alongside or instead of spatial extent. Accepts `YYYY`, `YYYY-MM`, `YYYY-MM-DD`.

- **Status workflow documentation** — all 6 publication statuses (Draft, Harvested, Contributed, Published, Testing, Withdrawn) documented in README with transitions and visibility rules.

- **Burger menu navigation** — top-bar hamburger menu with links to all main pages.

- **Human-readable sitemap** — `/pages` lists all pages with descriptions, organised by category.

- **Custom error pages** — styled 404 and 500 pages matching the application design.

- **"View work details" button on map popups** linking to the work landing page.

- **Paginated popup for overlapping features** — Previous/Next navigation when multiple works overlap.

- **Point geometry highlighting** — circle markers show visual feedback when selected (gold/orange).

- **Admin unpublish action** — admins can unpublish a work, changing status from Published to Draft.

- **RSS/Atom feed harvesting support** alongside OAI-PMH.

- **`harvest_journals` management command** — CLI tool for harvesting from real journal sources with progress reporting.

- **Test coverage** — 40+ tests covering temporal contribution, status workflow, RSS harvesting, and live journal harvesting.

### Changed

- **Contribution page pagination** — `/contribute/` paginates with configurable page size (default 50, max 200).

- **Model terminology alignment** — `Publication` renamed to `Work` throughout. API endpoint changes from `/api/v1/publications/` to `/api/v1/works/`, sitemap to `/sitemap-works.xml`, URL pattern to `/work/<id>/`. Django app renamed from `publications/` to `works/`.

- **Work type taxonomy** — `type` field added with 39 work types (Crossref/OpenAlex vocabulary). Set from source's `default_work_type`; overridden by OpenAlex when available.

- **Removed external CDN dependencies** — all JS and CSS libraries served locally.

- **Improved map accessibility** — keyboard navigation and screen reader support.

- **Regional subscription email notifications** — emails group works by region; each section shows region name, type, count, and a link.

- **Unified contribution workflow** — single "Submit contribution" button covers spatial and/or temporal extent in one action.

- **Unified admin control panel** — admin status, publish/unpublish, provenance, and "Edit in Admin" consolidated into one box at the top of the work landing page.

- **Improved text wrapping** — page titles and abstracts wrap on narrow windows.

- **Unified URL structure** — ID-based URLs changed from `/publication/<id>/` to `/work/<id>/`.

- **Consolidated work identifier logic** — new `Work.get_identifier()` returns the DOI when available, falling back to the internal ID.

- **Refactored `views_geometry.py`** — DOI-based functions wrap ID-based functions; ~36 % reduction.

- **Renamed "Locate" to "Contribute"** — URL, page title, and navigation updated.

- **Contribute page layout refactored** — text overflow fixed.

- **Flexible publishing requirements** — harvested works with geometry can be published directly without requiring user contribution.

- **Contribute page login button improved** — informational disabled button: "Please log in to contribute (user menu at top right)".

- **Simplified footer navigation** — Sitemap, About/Contact/Imprint, Privacy, and data license only. Other links moved to burger menu and sitemap.

### Fixed

- **JavaScript scope error** — `drawnItems is not defined` on the contribution form.

- **GeoJSON geometry detection** — map click detection now reads `layer.feature.geometry` directly, with point-in-polygon (ray casting), point-on-line, and point detection.

- **Map popup null location error** — paginated popup no longer crashes; existing popup is closed before setting a new location.

- **Highlight persistence after popup close** — geometries return to default style when popups close.

- **Individual popups during pagination** — individual feature popups no longer open simultaneously with the paginated popup.

- **Close button highlight clearing** — popup close (X) and ESC clear geometry highlights.

- **First-page highlight race condition** in the paginated popup.

- **CircleMarker style properties** — point geometries use `radius` instead of `dashArray` for proper visual feedback.
