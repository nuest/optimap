# SPDX-FileCopyrightText: 2026 OPTIMETA and KOMET projects <https://projects.tib.eu/komet>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Shared helpers used by every harvester (OAI-PMH, RSS, Crossref, MaRESS).

This module contains:
- HarvestStats and HarvestWarningCollector — accumulators threaded through parsers.
- The dedup / careful-update helpers (`_save_or_update_work` and friends).
- Small utilities used by parsers: `parse_publication_date`, `_get_article_link`,
  `get_or_create_admin_command_user`.
- Completion / failure / notification helpers that replace the previously
  duplicated success/failure/email blocks at the bottom of each harvester.
"""

import logging
import re

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.mail import send_mail
from django.utils import timezone

from works.models import Work

logger = logging.getLogger(__name__)
User = get_user_model()


class HarvestStats:
    """Tally of `_save_or_update_work` outcomes for one harvest run.

    Each parser increments the matching counter at the call site. The harvester
    then persists `created` to `HarvestingEvent.records_added`, `updated` to
    `records_updated`, and uses the totals in the completion email.
    """

    __slots__ = (
        "created",
        "updated",
        "doi_backfilled",
        "skipped_same_source",
        "skipped_cross_source",
        "skipped_existing",
    )

    def __init__(self):
        self.created = 0
        self.updated = 0
        self.doi_backfilled = 0
        self.skipped_same_source = 0
        self.skipped_cross_source = 0
        self.skipped_existing = 0

    @property
    def skipped(self):
        return self.skipped_same_source + self.skipped_cross_source + self.skipped_existing

    def record(self, action):
        if action == "created":
            self.created += 1
        elif action == "updated":
            self.updated += 1
        elif action == "doi_backfilled":
            self.doi_backfilled += 1
        elif action == "skipped_same_source":
            self.skipped_same_source += 1
        elif action == "skipped_cross_source":
            self.skipped_cross_source += 1
        elif action == "skipped_existing":
            self.skipped_existing += 1


class HarvestWarningCollector(logging.Handler):
    """
    Custom logging handler to collect warning and error messages during harvesting.

    This handler collects messages for email summaries while also ensuring they are
    logged to the standard output/error through the normal logging chain.

    Categorizes messages with emoji severity indicators:
    - 🔴 ERROR: Critical errors that prevented processing
    - 🟡 WARNING: Issues that didn't prevent processing but need attention
    - 🔵 INFO: Important informational messages
    """

    def __init__(self, passthrough=True):
        super().__init__()
        self.warnings = []
        self.errors = []
        self.info = []
        self.passthrough = passthrough

    def emit(self, record):
        message = self.format(record)
        if record.levelno >= logging.ERROR:
            self.errors.append(f"🔴 ERROR: {message}")
        elif record.levelno >= logging.WARNING:
            self.warnings.append(f"🟡 WARNING: {message}")
        elif record.levelno >= logging.INFO and any(
            keyword in message.lower() for keyword in ["no openalex match", "openalex matching failed", "skipping"]
        ):
            self.info.append(f"🔵 INFO: {message}")

    def get_summary(self):
        """Return a formatted summary of all collected messages."""
        summary_parts = []

        if self.errors:
            summary_parts.append(f"\n{'=' * 70}\n🔴 ERRORS ({len(self.errors)})\n{'=' * 70}")
            summary_parts.extend(self.errors)

        if self.warnings:
            summary_parts.append(f"\n{'=' * 70}\n🟡 WARNINGS ({len(self.warnings)})\n{'=' * 70}")
            summary_parts.extend(self.warnings)

        if self.info:
            summary_parts.append(f"\n{'=' * 70}\n🔵 NOTABLE INFORMATION ({len(self.info)})\n{'=' * 70}")
            summary_parts.extend(self.info)

        if not (self.errors or self.warnings or self.info):
            return "\n✅ No warnings or errors during harvesting!"

        return "\n".join(summary_parts)

    def has_issues(self):
        return bool(self.errors or self.warnings or self.info)


def get_or_create_admin_command_user():
    """Get or create the system user that owns harvested publications."""
    username = "django_admin_command"
    email = "django_admin_command@system.local"
    user, created = User.objects.get_or_create(
        username=username,
        defaults={
            "email": email,
            "is_active": False,
            "is_staff": False,
        },
    )
    if created:
        logger.info("Created system user: %s", username)
    return user


def ensure_collection_for_source(source):
    """Make sure ``source.collection`` is set, creating a Collection on first
    harvest if needed.

    Called from every harvest entry point (OAI-PMH / OJS / Janeway, the
    Mountain Wetlands API, OpenAlex-as-source). Issue #192 originally asked
    the generic OAI-PMH harvester to "create a collection for each endpoint
    based on the provided metadata"; the same auto-creation now applies to
    the other harvesters so admins don't have to pre-seed collections via
    fixtures or the admin UI. The Collection is keyed by a slug derived from
    the source's name (with a numeric suffix if the slug already exists under
    a different source) and starts ``is_published=False`` so admins can
    review name/description before exposing it on ``/collections/``.

    Returns the (possibly newly-created) ``Collection``, or ``None`` when the
    source has no usable name to derive a slug from. No-op when
    ``source.collection`` is already set.
    """
    # Avoid a circular import: works.models imports works.harvesting via tasks.
    from django.utils.text import slugify

    from works.models import Collection

    if source.collection_id is not None:
        return source.collection
    base_name = (source.name or "").strip()
    if not base_name:
        logger.warning(
            "Source id=%s has no name — cannot auto-create a Collection.",
            source.id,
        )
        return None
    base_slug = slugify(base_name)[:100] or f"source-{source.id}"
    identifier = base_slug
    suffix = 2
    while Collection.objects.filter(identifier=identifier).exists():
        identifier = f"{base_slug}-{suffix}"[:100]
        suffix += 1
    collection = Collection.objects.create(
        identifier=identifier,
        name=base_name,
        description="",
        homepage_url=source.homepage_url or None,
        # Start unpublished — admins curate name/description and flip the
        # toggle when the collection is ready to be public.
        is_published=False,
    )
    source.collection = collection
    source.save(update_fields=["collection"])
    logger.info(
        "Auto-created Collection %r (id=%s) for source id=%s (%s)",
        identifier,
        collection.id,
        source.id,
        base_name,
    )
    return collection


def _get_article_link(work):
    """Prefer our site permalink if DOI exists, else fallback to original URL."""
    if getattr(work, "doi", None):
        base = settings.BASE_URL.rstrip("/")
        return f"{base}/work/{work.doi}"
    return work.url


def parse_publication_date(date_string):
    """Normalise mixed date strings to YYYY-MM-DD; falls back to Jan 1 of any year."""
    if not date_string:
        return None
    date_string = date_string.strip()
    if re.match(r"^\d{4}-\d{2}-\d{2}$", date_string):
        return date_string
    if re.match(r"^\d{4}-\d{2}$", date_string):
        return f"{date_string}-01"
    if re.match(r"^\d{4}$", date_string):
        return f"{date_string}-01-01"
    year_match = re.search(r"\b(\d{4})\b", date_string)
    if year_match:
        return f"{year_match.group(1)}-01-01"
    logger.warning("Could not parse date format: %s", date_string)
    return None


# -----------------------------------------------------------------------------
# Harvest dedup + careful-update helpers (used by every harvester).
#
# Dedup is per-source: a Work that already exists *under the same Source* is
# the trigger for either skipping or updating. A Work that exists under a
# *different* Source is logged and skipped — OPTIMAP does not currently
# attempt to merge metadata across sources for the same article (see
# docs/manage.md "Deduplication and updates"). Without per-source scoping, the
# Source.{url,doi} model uniqueness would still catch the second insert at
# the DB level, but with an IntegrityError; the explicit pre-check is
# cleaner and lets the caller distinguish same-source vs cross-source.
#
# update_existing=True opts a harvester into in-place updates instead of
# skipping same-source duplicates. The update is *careful*:
#   - geometry / timeperiod_startdate / timeperiod_enddate are preserved
#     if the new harvest delivers nothing for them (the existing values
#     may be user contributions that the source still does not provide);
#   - status and created_by are never overwritten (curation state and
#     audit provenance must survive re-harvest);
#   - provenance.harvest / metadata_sources / openalex_match are refreshed
#     from the new harvest, but provenance.events is preserved and gets
#     a new "harvest_update" entry appended.
# -----------------------------------------------------------------------------

_HARVEST_PRESERVE_IF_NEW_EMPTY = ("geometry", "timeperiod_startdate", "timeperiod_enddate")
_HARVEST_NEVER_OVERWRITE = ("status", "created_by", "creationDate")


def _is_empty_for_update(value):
    """True when a freshly harvested field value carries no information that
    should overwrite an existing one."""
    if value is None:
        return True
    if isinstance(value, list) and not value:
        return True
    if hasattr(value, "empty") and getattr(value, "empty"):
        return True
    return False


def _find_existing_work(doi=None, url=None):
    """Return any Work matching ``doi`` or ``url`` (regardless of source)."""
    if doi:
        existing = Work.objects.filter(doi=doi).first()
        if existing:
            return existing
    if url:
        existing = Work.objects.filter(url=url).first()
        if existing:
            return existing
    return None


def _carefully_update_work(work, new_fields, event):
    """Update ``work`` in place from re-harvested ``new_fields``."""
    new_provenance = new_fields.pop("provenance", None)

    for field, new_value in new_fields.items():
        if field in _HARVEST_NEVER_OVERWRITE:
            continue
        if field in _HARVEST_PRESERVE_IF_NEW_EMPTY and _is_empty_for_update(new_value):
            continue
        setattr(work, field, new_value)

    existing_provenance = work.provenance if isinstance(work.provenance, dict) else {}
    if isinstance(new_provenance, dict):
        for key in ("harvest", "metadata_sources", "openalex_match"):
            if key in new_provenance:
                existing_provenance[key] = new_provenance[key]
    existing_provenance.setdefault("events", []).append(
        {
            "type": "harvest_update",
            "at": timezone.now().isoformat(),
            "harvesting_event_id": event.id if event else None,
        }
    )
    work.provenance = existing_provenance

    work.job = event
    work.save()
    return work


def _backfill_empty_doi(work, new_doi, event):
    """Populate an existing work's empty ``doi`` from a re-harvest.

    Some legacy works (notably AGILE-GISS records harvested via the old
    Copernicus OAI-PMH endpoint, which sometimes did not carry the DOI in
    ``dc:identifier`` / ``dc:relation``) ended up with ``doi=None``. When a
    later re-harvest from a richer source (Crossref, OpenAlex) finds the
    same work by URL it would otherwise skip — see the source-match /
    ``update_existing`` branches below — and the DOI gap would persist.

    This helper is the targeted exception: when the existing record has no
    DOI and the new harvest has one, write just the DOI (and bump
    ``lastUpdate`` and ``provenance.events``) regardless of source identity
    or ``update_existing``.
    """
    work.doi = new_doi
    existing_provenance = work.provenance if isinstance(work.provenance, dict) else {}
    existing_provenance.setdefault("events", []).append(
        {
            "type": "doi_backfill",
            "at": timezone.now().isoformat(),
            "doi": new_doi,
            "harvesting_event_id": event.id if event else None,
        }
    )
    work.provenance = existing_provenance
    # Include lastUpdate explicitly: with update_fields, auto_now fields are
    # not bumped automatically, and we want the work-landing cache key to
    # invalidate so the freshly populated DOI shows up immediately.
    work.save(update_fields=["doi", "provenance", "lastUpdate"])
    logger.info("Backfilled empty DOI on work id=%s with %s", work.id, new_doi)


def _save_or_update_work(work_kwargs, source, event, update_existing=False):
    """Create or update a Work, applying per-source dedup.

    Returns ``(work_or_none, action)`` where ``action`` is one of:
      * ``'created'`` — new Work was inserted,
      * ``'updated'`` — existing same-source Work was updated in place,
      * ``'doi_backfilled'`` — existing work had no DOI; only ``doi`` was filled in,
      * ``'skipped_same_source'`` — same-source duplicate, ``update_existing`` was False,
      * ``'skipped_cross_source'`` — different-source duplicate (never auto-merged).
    """
    doi_value = work_kwargs.get("doi")
    url_value = work_kwargs.get("url")

    existing = _find_existing_work(doi=doi_value, url=url_value)
    if existing is not None:
        # Targeted DOI backfill runs *before* the source-match / skip logic
        # so a legacy no-DOI work gets its DOI populated even from a
        # different-source re-harvest.
        backfilled = bool(doi_value) and not existing.doi
        if backfilled:
            _backfill_empty_doi(existing, doi_value, event)

        if existing.source_id != getattr(source, "id", None):
            logger.info(
                "Skipping cross-source duplicate %s — already harvested under source id=%s",
                doi_value or url_value,
                existing.source_id,
            )
            return existing, "doi_backfilled" if backfilled else "skipped_cross_source"
        if not update_existing:
            logger.debug(
                "Skipping same-source duplicate %s (use --update / update_existing=True to refresh)",
                doi_value or url_value,
            )
            return existing, "doi_backfilled" if backfilled else "skipped_same_source"
        _carefully_update_work(existing, work_kwargs, event)
        return existing, "updated"

    work = Work.objects.create(**work_kwargs)
    return work, "created"


# -----------------------------------------------------------------------------
# Completion / failure / notify helpers — replace the previously duplicated
# success and failure tail blocks across all four harvesters.
# -----------------------------------------------------------------------------


def resolve_user(user):
    """Admin actions enqueue with a user id rather than a pickled User instance."""
    if isinstance(user, int):
        return User.objects.filter(pk=user).first()
    return user


def count_spatial_temporal(event):
    """Return ``(spatial_count, temporal_count)`` for works attached to ``event``."""
    spatial = Work.objects.filter(job=event).exclude(geometry__isnull=True).count()
    temporal = Work.objects.filter(job=event).exclude(timeperiod_startdate=[]).count()
    return spatial, temporal


def complete_harvest(event, stats, warning_collector, spatial_count=None, temporal_count=None):
    """Stamp success-state counters and timestamps on a HarvestingEvent.

    ``spatial_count`` and ``temporal_count`` default to the standard
    ``count_spatial_temporal`` query; harvesters with non-standard semantics
    (e.g. MWR, where every work has a non-null geometry but it may be an
    empty GeometryCollection) can pass pre-computed values.

    Returns ``(spatial_count, temporal_count)`` so callers can include them
    in the harvest-summary email body.
    """
    if spatial_count is None or temporal_count is None:
        s, t = count_spatial_temporal(event)
        if spatial_count is None:
            spatial_count = s
        if temporal_count is None:
            temporal_count = t
    event.status = "completed"
    event.completed_at = timezone.now()
    event.records_added = stats.created
    event.records_updated = stats.updated
    event.records_skipped = stats.skipped
    event.records_with_spatial = spatial_count
    event.records_with_temporal = temporal_count
    event.log_text = warning_collector.get_summary()
    event.save()
    return spatial_count, temporal_count


def fail_harvest(event, exc, warning_collector):
    """Stamp failure state on a HarvestingEvent and persist the log + error message."""
    event.status = "failed"
    event.completed_at = timezone.now()
    event.error_message = str(exc)[:1000]
    event.log_text = warning_collector.get_summary()
    event.save()


def send_harvest_email(user, subject, body, fail_silently=False):
    """Guarded send_mail. No-op when the user has no email."""
    if not user or not user.email:
        return
    try:
        send_mail(
            subject,
            body,
            settings.EMAIL_HOST_USER,
            [user.email],
            fail_silently=fail_silently,
        )
    except Exception as e:  # noqa: BLE001 — email failure must not crash the harvest
        logger.error("Failed to send harvest email to %s: %s", user.email, e)


def render_harvest_email(template_name, context):
    """Render a harvest email template and split subject from body.

    Returns ``(subject, body)``. Delegates to ``works.utils.email.render_email``
    so autoescape is off (plain-text output — no HTML entities in URLs, etc.).
    """
    from works.utils.email import render_email

    return render_email(template_name, context)
