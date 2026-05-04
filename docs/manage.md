# Managing OPTIMAP

This document is the admin / operator handbook for an OPTIMAP instance. It is a counterpart to [README.md](../README.md) (which targets developers and deployers) and [CLAUDE.md](../CLAUDE.md) (which targets coding assistants): everything here assumes you have a running OPTIMAP and are signed in to `/admin/` as a Django superuser.

For a fully working setup, two processes must be live in addition to the web app:

- the database (PostGIS) — required for everything;
- the Django-Q cluster (`python manage.py qcluster`) — required for harvesting, scheduled emails, and data dumps. The admin will accept actions without it, but they will silently sit in the queue.

## Manage harvesting

Sources and harvesting events are managed entirely through the Django admin under `/admin/works/source/` and `/admin/works/harvestingevent/`. As of v0.12.0 (issue #228) the `Source` model is registered with a dedicated admin and `HarvestingEvent` exposes the full per-run log, error message, and record counts.

### Configure a source

At `/admin/works/source/`, the changelist shows each source's name, OA / preprint flags, last harvest time, harvest interval, latest event status (linked to the event), and total event count. Search runs over `name`, `url_field`, `issn_l`, `publisher_name`, and `openalex_id`. Filter by `is_oa`, `is_preprint`, and `default_work_type`.

Open a source to edit its OAI-PMH URL, source type (`oai-pmh` / `ojs` / `janeway` / `rss` / `crossref-prefix` / `mountain-wetlands`), collection (FK to a `Collection`), harvest interval, default work type, and OpenAlex metadata. **A `Source` is auto-scheduled only when both `source_type` is a schedulable kind *and* `harvest_interval_minutes > 0`** — saving creates a recurring Django-Q `Schedule` named `Harvest Source <id>` that calls the right task per source type. The default for new sources is `harvest_interval_minutes = 0` (manual-only); set it to a positive number to enable auto-scheduling. The change page also lists the five most recent `HarvestingEvent`s for the source inline, with links into each event.

> **Source.collection is optional at create time, but always populated by the time the first harvest finishes.** Leaving the collection field blank when you create a Source is **not** an error:
> - **OAI-PMH / OJS / Janeway sources** auto-create a Collection on first harvest, slugged from the source name (e.g. `"Earth System Science Data"` → identifier `earth-system-science-data`). The new Collection starts **unpublished** so it does not show up on `/collections/` until you review the auto-derived name and description and flip `is_published`. Review auto-created collections at `/admin/works/collection/?is_published__exact=0` before publishing.
> - **RSS / Crossref / MaRESS sources** don't auto-create — they get their Collection from `harvest_journals --insert-sources` instead. If you leave `Source.collection` blank for one of these and run a harvest, the works simply aren't added to any collection, and curators can add them by hand from each work landing page later.
> 
> Either way, when a collection **is** set on the source, every work created during harvest is automatically added to it (additive — pre-existing memberships under other collections are preserved). To put a fresh source's harvest into a specific Collection, create the target Collection first under `/admin/works/collection/` and link it from the Source change page; see "Create a new collection (no harvest needed)" below.

### Trigger or schedule a harvest from the admin

Select one or more sources in the changelist and pick an action from the **Action** dropdown:

| Action | What it does |
| --- | --- |
| **Trigger harvesting for selected sources** | Enqueues an immediate `async_task('works.tasks.harvest_oai_endpoint', source.id, user.id)` per selected source. Returns immediately. |
| **Trigger harvesting for all sources** | Same, but enqueues every `Source` in the database. Useful after a cluster restart or to force a full refresh. |
| **Schedule harvesting for selected sources** | Creates a one-off `Schedule` named `Manual Harvest Source <id>` that runs at the next cluster tick. Skips sources that already have such a schedule (you'll get a warning message). |

All three actions are **non-blocking**: they queue work and return. Progress is observed at `/admin/works/harvestingevent/`.

> **Why async?** Earlier versions ran the harvest synchronously inside the admin request, which routinely tripped gunicorn's worker timeout on non-trivial sources. The new actions hand off to Django-Q immediately. The cluster must be running for them to actually execute.

CLI alternatives still work and are documented in README §[Harvest Publications from real journals](../README.md#harvest-publications-from-real-journals): `python manage.py harvest_journals --journal <slug>` (with `--list`, `--all`, `--create-sources`, `--user-email`, `--max-records`).

**Recover from a thundering-herd schedule state:** `python manage.py reset_harvest_schedules` rebuilds every `Harvest Source <id>` recurring schedule with a properly deferred `next_run` and (by default) staggers them across the smallest harvest interval so the cluster doesn't get hit with every source at once. Use this after a bulk `--insert-sources` run on a deployment that pre-dated the `Source.save()` fix, or any time you find every source firing simultaneously. Flags: `--dry-run` (preview), `--no-stagger` (set every `next_run` to `now + its own interval`), `--clear-manual` (also delete leftover `Manual Harvest Source <id>` one-off rows from the admin "Schedule harvesting" action).

**Bootstrap the admin from the journal config:** `python manage.py harvest_journals --insert-sources` creates one `Source` row per (enabled) entry in `harvest_journals`'s `SOURCE_CONFIG` without harvesting. Each insert also gets-or-creates a `Collection` from the entry's `collection_name`. After running it, every configured journal appears at `/admin/works/source/` (linked to its collection) and can be triggered with the actions above. Re-running is idempotent (existing rows by name or URL are left alone). Add `--include-disabled` to insert journals whose upstream is currently broken (e.g. the Copernicus OAI-PMH 404). All inserts default to `harvest_interval_minutes = 0` (manual-only) so the cluster is not flooded after a bulk insert; `Source.save()` dispatches to the correct task per source type when you later raise the interval.

### Inspect harvesting events

At `/admin/works/harvestingevent/`, each row is one harvest run. The changelist shows:

- `id`, linked `source`, `status` (`pending` / `in_progress` / `completed` / `failed`),
- `started_at` and a computed `duration` (`Ns` or `Nm Ms`),
- `records_added`, `records_with_spatial`, `records_with_temporal`,
- a truncated `error_message` (full text on the change page).

Filter by `status`, `source`, or the `started_at` date hierarchy. Free-text search runs across `source__name`, `source__url_field`, `error_message`, **and the full `log_text`** — so you can search the logs directly for things like a problematic DOI or a parse-error string.

Open an event to see the full log in a scrollable `<pre>` block. The log is the summary captured by `HarvestWarningCollector` during the run and uses prefix glyphs for severity:

- 🔴 errors (e.g. fatal upstream failures, parse errors that aborted a record),
- 🟡 warnings (e.g. records skipped, individual fields ignored),
- 🔵 notable info (e.g. fallback geometry sources used).

Events are machine-created — manual `add` is disabled in the admin. To re-run a failed source, select one or more events and choose **Retry selected harvesting events**: this re-enqueues `harvest_oai_endpoint` for each event's source via `async_task`. A new `HarvestingEvent` row will appear per source; the original `failed` event is left in place as history.

### Deduplication and updates

Every harvester (OAI-PMH, RSS, Crossref, MaRESS) routes its inserts through a shared helper that looks up an existing Work by DOI or URL **scoped to the harvest's `Source`** before deciding what to do. Four outcomes:

| Pre-existing match | `--update` flag | Outcome |
| --- | --- | --- |
| None | n/a | New Work created. |
| Same `Source` | off (default) | Duplicate skipped silently. |
| Same `Source` | on | Existing Work updated in place — see "Careful update" below. |
| Different `Source` | n/a | Skipped with an info log message. **Cross-source merging is not handled.** |

> **OPTIMAP does not currently merge metadata across sources.** When the same DOI/URL is exposed by two different sources (e.g. a journal article also surfaced via a preprint server), the second source's harvest is logged and skipped — the first source "owns" the Work. There is no automatic union of fields, no cross-source provenance trail, and no way to switch ownership without manual admin intervention. If this becomes a frequent need, open a follow-up issue.

#### Careful update (`--update` flag)

`python manage.py harvest_journals --update` (or `update_existing=True` on the task functions) refreshes existing same-source works in place. The update is deliberately conservative:

- **Preserved when the new harvest brings nothing for them:** `geometry`, `timeperiod_startdate`, `timeperiod_enddate`. These often come from a user contribution through OPTIMAP that the source still does not provide; we don't want to wipe a curator's work because the upstream record is silent on coordinates.
- **Never overwritten:** `status` (a Published Work stays Published, never flips back to Harvested) and `created_by` (audit trail).
- **Refreshed from the new harvest:** title, abstract, authors, keywords, topics, OpenAlex enrichment fields, the `provenance.harvest` and `provenance.metadata_sources` and `provenance.openalex_match` sections, and the `Source` FK.
- **Audit trail:** a `harvest_update` event is appended to `Work.provenance.events` (existing events including user contributions are preserved).

Use `--update` when you want OpenAlex enrichment to re-run on previously-harvested works (e.g. after a matcher change), or when an upstream metadata change should propagate without losing curator additions. Without it, re-running the harvester is a no-op for already-known records.

### Email notifications on completion / failure

`harvest_oai_endpoint` sends a result email to the user that triggered the run (the user who clicked the action; falls back to silently skipping if there is no user). Subject lines are `✅ Harvesting Completed for <collection>` or `❌ Harvesting Failed for <collection>`. To debug locally, point Django at the console backend in `.env`:

```env
EMAIL_BACKEND=django.core.mail.backends.console.EmailBackend
```

### Where things live in code

For maintainers cross-referencing the admin features above:

- Admin classes & actions: [works/admin.py](../works/admin.py) — `SourceAdmin`, `HarvestingEventAdmin`, `RecentHarvestingEventInline`, `_enqueue_harvest`, `trigger_harvesting_for_specific`, `trigger_harvesting_for_all`, `schedule_harvesting`, `retry_event`.
- Harvesters: [works/harvesting/](../works/harvesting/) — one module per source type (`oai.py`, `rss.py`, `crossref.py`, `mountain_wetlands.py`), with shared helpers in `common.py` (HarvestStats, dedup helpers, `complete_harvest` / `fail_harvest` / `send_harvest_email`), `sessions.py` (HTTP session factories), `metadata_html.py` (geometry + temporal extraction), and `openalex.py`. Persists `records_added`, `records_updated`, `records_with_spatial`, `records_with_temporal`, `log_text`, and `error_message` (truncated to 1000 chars) on the event. The public entry points are re-exported from [works/tasks.py](../works/tasks.py) so Django-Q dotted-path schedules (e.g. `works.tasks.harvest_oai_endpoint`) keep working.
- Models: [works/models.py](../works/models.py) — `Source`, `HarvestingEvent` (`error_message`, `log_text`, `records_added`, `records_with_spatial`, `records_with_temporal`; index on `(source, -started_at)`).
- Migration: [works/migrations/0003_harvestingevent_error_message_and_more.py](../works/migrations/0003_harvestingevent_error_message_and_more.py).
- Tests: [tests/test_admin_harvesting.py](../tests/test_admin_harvesting.py), [tests/test_regular_harvesting.py](../tests/test_regular_harvesting.py).

## Manage collections

A **`Collection`** groups works under a curated identifier — typically a journal (`scientific-data`, `eartharxiv`), a thematic dataset (`mountain-wetlands`), or a community-curated series (`agile-gi`). A `Work` can belong to **multiple** collections (`Work.collections`, M2M). Each `Source` has an optional default `collection`, so works harvested from that source can be tagged automatically.

### Public surfaces

- `/collections/` — index of all *published* collections (anonymous-visible). Staff users see unpublished collections too, with inline publish/unpublish buttons.
- `/collections/<identifier>/` — detail page for one collection: map of works, work cards, links to the external homepage if set.
- `/<short_slug>/` — optional vanity URL that 301-redirects to the canonical detail page. Useful for short, citable URLs (e.g. `/agile-gi`). Set `short_slug` in admin to opt in.
- Both `/collections/` and each published `/collections/<identifier>/` page are listed in `sitemap.xml` (machine) and `/pages/` (human-readable).

### Create a new collection (no harvest needed)

A collection does **not** need a harvested source. A curator can build one entirely by hand from existing works.

1. Go to `/admin/works/collection/add/`.
2. Fill in `name` — `identifier` is auto-suggested from the name (URL-safe slug); edit it if you want a different URL. The detail page will live at `/collections/<identifier>/`.
3. Optional fields:
   - `short_slug` — vanity URL: `/<short_slug>/` 301-redirects to the canonical detail page (e.g. `agile-gi` for the AGILE conference series). Pick something distinctive enough not to collide with future top-level routes.
   - `description` — Markdown-friendly text shown on the detail page.
   - `homepage_url` — external homepage shown as a link in the detail-page header.
4. Add `curators` (see "Promote a user to curator" below) and check `is_published` when you want it visible to anonymous users and listed in sitemaps. Leave `is_published` unchecked while staging — staff users will still see it under `/collections/`, marked as **Unpublished**.
5. Save.

To **populate the collection**, sign in as a curator (or staff user) and visit any `/work/<DOI>/` landing page: an "Add to **{Collection}**" button appears for every collection you curate, and a "Remove from **{Collection}**" button replaces it once the work is in. Memberships are independent — a single work can be added to several collections, and removing it from one leaves the others intact. For bulk assignment, use the `Work` admin's `collections` filter horizontal widget on individual works, or call `work.collections.add(collection)` from `python manage.py shell` for scripted bulk additions.

### Promote a user to curator

A curator is just a user listed in a `Collection.curators` (M2M to `CustomUser`). There is no separate role or permission to grant — staff status is **not** required.

Two ways to add curators:

1. **From the collection's change page (recommended for one-off):** open `/admin/works/collection/<id>/change/`, scroll to the **Curators** widget (a Django `filter_horizontal` two-pane selector), pick the user(s) on the left, click the right-arrow to move them into the chosen list, and Save. Search by username/email in the widget's filter box.
2. **From the user's perspective (recommended when granting one user access to many collections):** there is no admin-side mirror widget on `CustomUser` today, so use the shell:
   ```bash
   python manage.py shell -c "
   from django.contrib.auth import get_user_model
   from works.models import Collection
   user = get_user_model().objects.get(email='curator@example.com')
   for slug in ['mountain-wetlands', 'agile-gi']:
       Collection.objects.get(identifier=slug).curators.add(user)
   "
   ```

Once added, the user immediately sees curator buttons on `/work/<DOI>/` landing pages for those collections — no logout/login required. To revoke, deselect the user in the same widget (or `collection.curators.remove(user)` in the shell).

If a user does not yet exist (e.g. you want to invite an external collaborator to curate `agile-gi`), have them sign in once via the magic-link flow at `/loginconfirm/` to create their `CustomUser` row, then add them as a curator. Curators do not need `is_staff = True`; granting it would also give them access to the full Django admin, which is usually overkill for this role.

### Curate a collection

At `/admin/works/collection/`, the changelist shows each collection's name, identifier, short slug, publication state, and counts (works, curators, sources). Open a collection to:

- edit `name`, `description`, `homepage_url`,
- toggle `is_published` (only published collections are visible to anonymous users and listed in sitemaps),
- assign `curators` — a many-to-many to `CustomUser`. Curators get **Add to {X}** / **Remove from {X}** buttons on every work landing page in the OPTIMAP UI, scoped to the collections they curate.
- set an optional `short_slug` for the vanity redirect.

Bulk actions on the changelist: **Publish selected collections** and **Unpublish selected collections**.

### Inline admin controls in the public UI

Staff users see admin chrome integrated into the public pages:

- on `/collections/` — a status badge per row (Published / Unpublished) plus a one-click Publish/Unpublish button and a deep-link to the admin change page;
- on `/collections/<identifier>/` — a top-of-page banner with the same controls;
- on every work landing page — for users who curate at least one collection, an "Add to / Remove from" button per applicable collection.

These mirror the per-work admin controls on the work landing page (Publish / Unpublish / Edit in Admin), keeping the workflow consistent for both admins and curators.

### Source types

The `Source.source_type` choice field selects the harvester pipeline:

| value | dispatched task | typical usage |
|---|---|---|
| `oai-pmh` | `harvest_oai_endpoint` | Generic OAI-PMH endpoint, unknown platform |
| `ojs` | `harvest_oai_endpoint` | OJS journal (typically with the [geoMetadata OJS plugin](https://github.com/TIBHannover/geoMetadata)) |
| `janeway` | `harvest_oai_endpoint` | Janeway journal (typically with the [geometadata Janeway plugin](https://github.com/GeoinformationSystems/janeway_geometadata/)) |
| `rss` | `harvest_rss_endpoint` | RSS / Atom feed |
| `crossref-prefix` | `harvest_crossref_prefix` | Crossref `works` API filtered by DOI prefix |
| `mountain-wetlands` | `harvest_mountain_wetlands` | Bespoke harvester for the Mountain Wetlands Repository (MaRESS) |

`oai-pmh`, `ojs`, and `janeway` share the same harvester today; the distinction captures the platform so the metadata extractor's priority order (schema.org JSON-LD → `geo+json` link → `DC.SpatialCoverage` → `DC.box`) and admin UI can branch in future without another migration.

#### Mountain Wetlands Repository (MaRESS) — `mountain-wetlands` source type

The MaRESS harvester is bespoke because the API is Zotero-shaped, not OAI-PMH/RSS/Crossref:

- **Run it manually:** `python manage.py harvest_journals --journal mountain-wetlands` (also available as a one-click admin action on the Source). Auto-scheduling is intentionally off — `harvest_interval_minutes` defaults to 0 for this source type and the issue (#192) requires the harvest to be manual.
- **Geometry:** built from each item's `study_sites[].location.{latitude, longitude}`. One Point per site, wrapped in a `GeometryCollection`. Records without sites get an empty geometry.
- **Dates:** the API's `date` field is free-text and often year-only (e.g. `"1993"`). The harvester parses the four-digit prefix and stores Jan 1 of that year; both `timeperiod_startdate` and `_enddate` are set to the year string.
- **DOI / OpenAlex enrichment:** every MaRESS record currently has `DOI=null` and an empty `url`, so OpenAlex is the *only* path to a DOI. The harvester calls `build_openalex_fields(title, doi=None, author=<first author surname>)`. Results land in `Work.provenance.openalex_match.status`:
  - `verified` — strong title+author match; DOI extracted from `openalex_ids` and saved on the Work,
  - `candidate` — only partial matches; top hits stored in `Work.openalex_match_info` for curator follow-up,
  - `none` — no plausible match; the Work is still saved with the API metadata.
- **Idempotency:** the harvester uses each item's stable API URL (`<source.url_field>/<item-uuid>`) as `Work.url`. Re-running on the same payload is a no-op.
- **Provenance:** `Work.provenance.harvest.original_record` stashes the verbatim API record so curators can re-run enrichment without re-fetching upstream.

### Where things live in code

- Model: [works/models.py](../works/models.py) — `Collection`, plus `Work.collections` (M2M) and `Source.{source_type, collection}`.
- Views: [works/views_collections.py](../works/views_collections.py) — index, detail, vanity redirect, publish/unpublish, add/remove work mutations.
- Templates: [works/templates/collections.html](../works/templates/collections.html), [works/templates/collection_page.html](../works/templates/collection_page.html), and the curator-button block in [works/templates/work_landing_page.html](../works/templates/work_landing_page.html).
- Provenance helper: [works/utils/provenance.py](../works/utils/provenance.py) — `append_event(work, type, **fields)` for contribution / publish / unpublish events.
- Provenance template tag: [works/templatetags/optimap_extras.py](../works/templatetags/optimap_extras.py) — `render_provenance` renders `Work.provenance` JSON readably for admins/curators.
- Sitemap: [optimap/sitemaps.py](../optimap/sitemaps.py) — `CollectionsSitemap`.
- Migration: [works/migrations/0004_collections.py](../works/migrations/0004_collections.py) (`atomic = False`).
- Tests: [tests/test_collections.py](../tests/test_collections.py).

## Reference-manager / Zotero compatibility

Work landing pages (`/work/<id>/` and `/work/<doi>/`) and collection detail pages (`/collections/<id>/`) emit the metadata that the [Zotero browser connector](https://www.zotero.org/download/connectors) and other reference managers (Mendeley, ReadCube, Citation Web Linker, etc.) read. No setup required — when a reader visits a work landing page with the connector installed, the connector recognises it as a journal article and offers "Save to Zotero". On a published collection page it offers "Save to Zotero (multiple items)" so a curator's curated set can be imported in one click.

What populates in the reader's reference manager (when the OPTIMAP record has the data): title, authors, publication date, DOI, journal title, ISSN, abstract, keywords, language, publisher, volume, issue, page range, and a PDF URL when the harvested URL ends in `.pdf`. Volume / issue / page range are populated by the OpenAlex matcher only — the OAI-PMH, RSS, Crossref, and MaRESS harvesters do not currently capture them, so works that never matched against OpenAlex will be missing those four fields. The mechanics are Highwire Press `citation_*` meta tags + `ScholarlyArticle` JSON-LD + a COinS span fallback, all built in [works/seo.py](../works/seo.py) and rendered from [works/templates/work_landing_page.html](../works/templates/work_landing_page.html) and [works/templates/collection_page.html](../works/templates/collection_page.html).

## Block emails and domains (anti-spam)

OPTIMAP can block specific email addresses and entire domains from registering or attempting to log in.

**What it does:**

- Blocks specific emails and entire domains from registering.
- Prevents login attempts from blocked users.
- Lets an admin delete users and instantly block their email and/or domain in a single action.

**Where to manage it:**

- `/admin/works/blockedemail/` — individual addresses.
- `/admin/works/blockeddomain/` — whole domains.

**How to use it:**

1. **Manually add a blocked email or domain.** Go to `/admin/works/blockedemail/` (or `blockeddomain/`) and add a new entry.
2. **Block users via an admin action.** Go to `/admin/auth/user/`, select the offending users, and pick **"Delete user and block email"** or **"Delete user and block email and domain"** from the **Action** dropdown. The user row is deleted and the corresponding blocklist entry is created in the same action.

The blocklist is consulted at signup and at magic-link login time; blocked entries are rejected before any email is sent.

## Operate the Django-Q cluster

OPTIMAP uses [Django-Q2](https://django-q2.readthedocs.io/) to schedule and run background work — harvesting, monthly subscription emails, GeoJSON / GeoPackage cache regeneration, and the one-off retry / trigger actions in the harvesting admin. **The cluster must be running for any of those to actually execute.** The admin will accept actions while the cluster is down, but the queued tasks will sit in `django_q_task` until a worker picks them up.

**Run the cluster:**

```bash
python manage.py qcluster
```

In Docker the cluster is started by `etc/manage-and-run.sh`; in a manual deployment, run it under `systemd` (or `supervisord`) so it restarts on failure.

**Monitor:**

The Django-Q [monitor docs](https://django-q2.readthedocs.io/en/master/monitor.html) cover this in depth. The two commands worth knowing:

```bash
python manage.py qmonitor   # live dashboard of cluster activity
python manage.py qinfo      # one-shot stats: cluster status, queue depth, last successes/failures
```

**Inspect and prune schedules and tasks** under `/admin/django_q/`:

- **Scheduled tasks** (`/admin/django_q/schedule/`) — every recurring schedule, including the `Harvest Source <id>` rows created by `Source.save()` and the `Manual Harvest Source <id>` one-offs created by the admin "Schedule harvesting" action. Stale or duplicate rows can be deleted here directly.
- **Successful** / **Failed** tasks (`/admin/django_q/success/`, `/failure/`) — completed task history with full stack traces on failure. Useful for diagnosing harvests that died before their `HarvestingEvent.error_message` could be persisted.

**Common failure modes:**

- **Stale dotted paths.** Pre-v0.12.0 schedules referenced `publications.tasks.*` instead of `works.tasks.*`. Long-lived deployments may still have these — the cluster fails them with `ImportError`. Delete them from `/admin/django_q/schedule/` and re-create them by saving the corresponding `Source` (or run `python manage.py reset_harvest_schedules`).
- **Thundering herd after `harvest_journals --insert-sources`.** Pre-fix `Source.save()` created Schedule rows with `next_run = now`. Recover with `python manage.py reset_harvest_schedules` (see "Manage harvesting" → "Recover from a thundering-herd schedule state").
- **Cluster down, queue grows.** Restart `qcluster` and watch `qinfo` — the queue drains in roughly the order tasks were enqueued. To skip the backlog, truncate `django_q_ormq` from the dbshell or via the `/admin/django_q/` views.

---

## Suggested further sections

The following sections are **suggested, not yet written**. They cover the rest of the admin surface and are worth filling in as the corresponding features stabilise. Each entry lists what the section should cover and the relevant code/admin URLs so an author can pick one up without further investigation.

### Manage works (publications)

`/admin/works/work/` — the core `Work` model.

- The publication status workflow (`d` draft / `p` public) and the `make_public` / `make_draft` admin actions; cross-link to README §[Publication Status Workflow](../README.md#publication-status-workflow).
- Bulk import / export through `django-import-export` (`WorkAdmin` extends `ImportExportModelAdmin`).
- Editing geometry on the Leaflet map widget (`LeafletGeoAdmin`); WKT input via <https://wktmap.com/>.
- The "Email permalinks preview to me" action.
- How harvested vs. manually created works are distinguished (`job` foreing key to `HarvestingEvent`).

### Manage users and access

`/admin/works/customuser/`, `/admin/works/userprofile/`.

- The passwordless magic-link login (10-minute token expiry); the user-facing flow; how to manually grant superuser/staff in the admin.
- `createsuperuser` (CLI) — see README §[Create Superusers/Admin](../README.md#create-superusersadmin).
- `UserProfile` (extended attributes), `EmailLog` (sent-mail audit trail).
- Why login must use `localhost` not `127.0.0.1` during development (CSRF cookie domain).

### Manage subscriptions and notifications

`/admin/works/subscription/`.

- Spatial + temporal filter fields on `Subscription`; how the subscription monthly email is composed.
- The `schedule_subscription_email_task` and `schedule_monthly_email_task` Django-Q schedules (and the `Send Monthly Manuscript Email` admin action).
- How to test the monthly email locally with the console email backend.

### Manage the Recognition Board

`/admin/works/contribution/` (and the public `/recognition/` page).

- Adding / curating contributions, moderating display names.
- The `better-profanity` filter on usernames (CHANGELOG entry under v0.12.0); how to override a false positive manually.
- How the auto-generated `coolname` defaults are filtered before being suggested.

### Manage Wikidata export

`/admin/works/wikidataexportlog/`.

- What gets exported, on what cadence, and how to trigger an export.
- Reading the export log on the change page (mirrors the harvesting-event log pattern).

### Manage data dumps and caches

Cached files in `/tmp/optimap_cache/`; retention controlled by `OPTIMAP_DATA_DUMP_RETENTION` (default: 3).

- The `regenerate_geojson_cache` task and the `schedule_geojson` management command (recurring every 6 hours).
- How to force a regenerate from the Django shell (`async_task('works.tasks.regenerate_geojson_cache')`).
- Public download endpoints `/download/geojson/` and `/download/geopackage/`.

### Manage global regions and predefined feeds

- `python manage.py load_global_regions` — required once after initial setup; loads continent and ocean polygons into `GlobalRegion`.
  - On first run, auto-downloads continents (Esri World Continents) and oceans (MarineRegions Global Oceans and Seas v1, ~128 MB GPKG) into the cache directory.
  - If the simplified ocean GeoJSON is missing, calls `simplify_ocean_geometries` automatically — Shapely tolerance simplify + percentile-based small-hole removal — producing a ~4.7 MB file that gets loaded into `GlobalRegion`.
  - Tunables (env vars, see `.env.example`): `OPTIMAP_OCEAN_SIMPLIFICATION_TOLERANCE` (default `0.05`), `OPTIMAP_OCEAN_SIMPLIFICATION_PERCENTILE` (default `80.0`), `OPTIMAP_GLOBAL_REGIONS_DATA_DIR` (default: command dir; set to a non-volatile path like `/var/opt/optimap/data` for deployment).
  - To refresh: delete the relevant cached file(s) in the data dir (`goas_v01.gpkg`, `goas_v01_simplified.geojson`, `world_continents.geojson`) and re-run the command.
- `python manage.py simplify_ocean_geometries --tolerance <float> --percentile <float>` — re-run the simplification pass standalone (e.g. when retuning); writes `goas_v01_simplified.geojson` from `goas_v01.gpkg` in the data dir.
- How global feeds (`/feeds/georss/<slug>/`) resolve a slug to a `GlobalRegion`.

### Sync external metadata

- `python manage.py sync_source_metadata` — syncs metadata from configured OAI-PMH endpoints back into the `Source` rows.
- `python manage.py update_openalex_journals` — enriches `Source` records from the OpenAlex API.
- When to re-run each (e.g. after adding a new source, on a quarterly cadence).

### Operate the geoextent service

- Configuration knobs from CLAUDE.md §[Geoextent API Endpoints](../CLAUDE.md): `GEOEXTENT_MAX_FILE_SIZE_MB`, `GEOEXTENT_MAX_BATCH_SIZE_MB`, `GEOEXTENT_MAX_DOWNLOAD_SIZE_MB`, `GEOEXTENT_DOWNLOAD_WORKERS`.
- Known upstream bug (coordinate-order in `geoextent.fromRemote()`); how to detect it in the wild.
- Where logs surface for failed remote extractions.

### Backup and restore

- `pg_dump` / `pg_restore` for the PostGIS database (geometry-aware).
- Fixtures in `fixtures/` for test data; not a substitute for backups.
- Static / media files (`OPTIMAP_DATA_DUMP_RETENTION`-rotated dumps in `/tmp/optimap_cache/` are regenerable, not backups).

### Upgrade and migration runbook

- Where the version is bumped ([optimap/\_\_init\_\_.py](../optimap/__init__.py)) and how it surfaces in the UI / API.
- Running migrations (`migrate` is auto-applied via `etc/manage-and-run.sh` in Docker).
- Reviewing [CHANGELOG.md](../CHANGELOG.md) before each upgrade — especially "Changed" / "Removed" entries that may require admin action (e.g. v0.12.0 bumped the harvest task's dotted path).
