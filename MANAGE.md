# Managing OPTIMAP

This document is the admin / operator handbook for an OPTIMAP instance. It is a counterpart to [README.md](README.md) (which targets developers and deployers) and [CLAUDE.md](CLAUDE.md) (which targets coding assistants): everything here assumes you have a running OPTIMAP and are signed in to `/admin/` as a Django superuser.

For a fully working setup, two processes must be live in addition to the web app:

- the database (PostGIS) — required for everything;
- the Django-Q cluster (`python manage.py qcluster`) — required for harvesting, scheduled emails, and data dumps. The admin will accept actions without it, but they will silently sit in the queue.

## Manage harvesting

Sources and harvesting events are managed entirely through the Django admin under `/admin/works/source/` and `/admin/works/harvestingevent/`. As of v0.12.0 (issue #228) the `Source` model is registered with a dedicated admin and `HarvestingEvent` exposes the full per-run log, error message, and record counts.

### Configure a source

At `/admin/works/source/`, the changelist shows each source's name, OA / preprint flags, last harvest time, harvest interval, latest event status (linked to the event), and total event count. Search runs over `name`, `url_field`, `issn_l`, `publisher_name`, and `openalex_id`. Filter by `is_oa`, `is_preprint`, and `default_work_type`.

Open a source to edit its OAI-PMH URL, collection name, harvest interval, default work type, and OpenAlex metadata. **Saving a `Source` (re)creates a recurring Django-Q `Schedule` named `Harvest Source <id>` that fires every `harvest_interval_minutes` minutes** — this is automatic, you do not need to schedule it yourself. The change page also lists the five most recent `HarvestingEvent`s for the source inline, with links into each event.

### Trigger or schedule a harvest from the admin

Select one or more sources in the changelist and pick an action from the **Action** dropdown:

| Action | What it does |
| --- | --- |
| **Trigger harvesting for selected sources** | Enqueues an immediate `async_task('works.tasks.harvest_oai_endpoint', source.id, user.id)` per selected source. Returns immediately. |
| **Trigger harvesting for all sources** | Same, but enqueues every `Source` in the database. Useful after a cluster restart or to force a full refresh. |
| **Schedule harvesting for selected sources** | Creates a one-off `Schedule` named `Manual Harvest Source <id>` that runs at the next cluster tick. Skips sources that already have such a schedule (you'll get a warning message). |

All three actions are **non-blocking**: they queue work and return. Progress is observed at `/admin/works/harvestingevent/`.

> **Why async?** Earlier versions ran the harvest synchronously inside the admin request, which routinely tripped gunicorn's worker timeout on non-trivial sources. The new actions hand off to Django-Q immediately. The cluster must be running for them to actually execute.

CLI alternatives still work and are documented in README §[Harvest Publications from real journals](README.md#harvest-publications-from-real-journals): `python manage.py harvest_journals --journal <slug>` (with `--list`, `--all`, `--create-sources`, `--user-email`, `--max-records`).

**Recover from a thundering-herd schedule state:** `python manage.py reset_harvest_schedules` rebuilds every `Harvest Source <id>` recurring schedule with a properly deferred `next_run` and (by default) staggers them across the smallest harvest interval so the cluster doesn't get hit with every source at once. Use this after a bulk `--insert-sources` run on a deployment that pre-dated the `Source.save()` fix, or any time you find every source firing simultaneously. Flags: `--dry-run` (preview), `--no-stagger` (set every `next_run` to `now + its own interval`), `--clear-manual` (also delete leftover `Manual Harvest Source <id>` one-off rows from the admin "Schedule harvesting" action).

**Bootstrap the admin from the journal config:** `python manage.py harvest_journals --insert-sources` creates one `Source` row per (enabled) entry in `harvest_journals`'s `SOURCE_CONFIG` without harvesting. After running it, every configured journal appears at `/admin/works/source/` and can be triggered with the actions above. Re-running is idempotent (existing rows by name or URL are left alone). Add `--include-disabled` to insert journals whose upstream is currently broken (e.g. the Copernicus OAI-PMH 404). RSS and Crossref-prefix sources will appear in the admin but their auto-schedule and the admin trigger both call `works.tasks.harvest_oai_endpoint`, so for now those still need the CLI route to harvest correctly — the command prints a warning naming each affected source.

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

### Email notifications on completion / failure

`harvest_oai_endpoint` sends a result email to the user that triggered the run (the user who clicked the action; falls back to silently skipping if there is no user). Subject lines are `✅ Harvesting Completed for <collection>` or `❌ Harvesting Failed for <collection>`. To debug locally, point Django at the console backend in `.env`:

```env
EMAIL_BACKEND=django.core.mail.backends.console.EmailBackend
```

### Where things live in code

For maintainers cross-referencing the admin features above:

- Admin classes & actions: [works/admin.py](works/admin.py) — `SourceAdmin`, `HarvestingEventAdmin`, `RecentHarvestingEventInline`, `_enqueue_harvest`, `trigger_harvesting_for_specific`, `trigger_harvesting_for_all`, `schedule_harvesting`, `retry_event`.
- Task: [works/tasks.py](works/tasks.py) — `harvest_oai_endpoint(source_id, user=None, max_records=None)`. Persists `records_added`, `records_with_spatial`, `records_with_temporal`, `log_text`, and `error_message` (truncated to 1000 chars) on the event.
- Models: [works/models.py](works/models.py) — `Source`, `HarvestingEvent` (`error_message`, `log_text`, `records_added`, `records_with_spatial`, `records_with_temporal`; index on `(source, -started_at)`).
- Migration: [works/migrations/0003_harvestingevent_error_message_and_more.py](works/migrations/0003_harvestingevent_error_message_and_more.py).
- Tests: [tests/test_admin_harvesting.py](tests/test_admin_harvesting.py), [tests/test_regular_harvesting.py](tests/test_regular_harvesting.py).

---

## Suggested further sections

The following sections are **suggested, not yet written**. They cover the rest of the admin surface and are worth filling in as the corresponding features stabilise. Each entry lists what the section should cover and the relevant code/admin URLs so an author can pick one up without further investigation.

### Manage works (publications)

`/admin/works/work/` — the core `Work` model.

- The publication status workflow (`d` draft / `p` public) and the `make_public` / `make_draft` admin actions; cross-link to README §[Publication Status Workflow](README.md#publication-status-workflow).
- Bulk import / export through `django-import-export` (`WorkAdmin` extends `ImportExportModelAdmin`).
- Editing geometry on the Leaflet map widget (`LeafletGeoAdmin`); WKT input via <https://wktmap.com/>.
- The "Email permalinks preview to me" action.
- How harvested vs. manually created works are distinguished (`job` FK to `HarvestingEvent`).

### Manage users and access

`/admin/works/customuser/`, `/admin/works/userprofile/`.

- The passwordless magic-link login (10-minute token expiry); the user-facing flow; how to manually grant superuser/staff in the admin.
- `createsuperuser` (CLI) — see README §[Create Superusers/Admin](README.md#create-superusersadmin).
- `UserProfile` (extended attributes), `EmailLog` (sent-mail audit trail).
- Why login must use `localhost` not `127.0.0.1` during development (CSRF cookie domain).

### Manage subscriptions and notifications

`/admin/works/subscription/`.

- Spatial + temporal filter fields on `Subscription`; how the subscription monthly email is composed.
- The `schedule_subscription_email_task` and `schedule_monthly_email_task` Django-Q schedules (and the `Send Monthly Manuscript Email` admin action).
- How to test the monthly email locally with the console email backend.

### Block emails and domains (anti-spam)

`/admin/works/blockedemail/`, `/admin/works/blockeddomain/`.

- Existing content already in README §[Block Emails/Domains](README.md#block-emailsdomains) — move or summarise here.
- How the blocklist is consulted at signup / subscription time.

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
- How global feeds (`/feeds/georss/<slug>/`) resolve a slug to a `GlobalRegion`.

### Sync external metadata

- `python manage.py sync_source_metadata` — syncs metadata from configured OAI-PMH endpoints back into the `Source` rows.
- `python manage.py update_openalex_journals` — enriches `Source` records from the OpenAlex API.
- When to re-run each (e.g. after adding a new source, on a quarterly cadence).

### Operate the Django-Q cluster

- Starting / stopping (`python manage.py qcluster`); running it under systemd or in Docker.
- Live monitoring with `qmonitor` and `qinfo`.
- Inspecting and pruning the `Schedule` and `Task` tables in the admin (`/admin/django_q/`).
- Common failure modes: stale schedules with the old `publications.tasks.*` dotted path (fixed in v0.12.0 — but legacy rows may still exist on long-lived deployments and should be deleted or recreated).

### Operate the geoextent service

- Configuration knobs from CLAUDE.md §[Geoextent API Endpoints](CLAUDE.md): `GEOEXTENT_MAX_FILE_SIZE_MB`, `GEOEXTENT_MAX_BATCH_SIZE_MB`, `GEOEXTENT_MAX_DOWNLOAD_SIZE_MB`, `GEOEXTENT_DOWNLOAD_WORKERS`.
- Known upstream bug (coordinate-order in `geoextent.fromRemote()`); how to detect it in the wild.
- Where logs surface for failed remote extractions.

### Backup and restore

- `pg_dump` / `pg_restore` for the PostGIS database (geometry-aware).
- Fixtures in `fixtures/` for test data; not a substitute for backups.
- Static / media files (`OPTIMAP_DATA_DUMP_RETENTION`-rotated dumps in `/tmp/optimap_cache/` are regenerable, not backups).

### Upgrade and migration runbook

- Where the version is bumped ([optimap/\_\_init\_\_.py](optimap/__init__.py)) and how it surfaces in the UI / API.
- Running migrations (`migrate` is auto-applied via `etc/manage-and-run.sh` in Docker).
- Reviewing [CHANGELOG.md](CHANGELOG.md) before each upgrade — especially "Changed" / "Removed" entries that may require admin action (e.g. v0.12.0 bumped the harvest task's dotted path).
