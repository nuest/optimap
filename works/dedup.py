# SPDX-FileCopyrightText: 2026 OPTIMETA and KOMET projects <https://projects.tib.eu/komet>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Automatic cross-source deduplication driven by OpenAlex.

OpenAlex assigns one ``openalex_id`` (``W…``) per scholarly work and lists every
hosting copy under ``locations[]``. OPTIMAP harvests the same work from several
sources (e.g. an EarthArXiv preprint and the published journal version) as
separate ``Work`` rows. This module **automatically** merges rows that share an
``openalex_id`` — no human review:

- The version OpenAlex marks as ``primary_location`` becomes the OPTIMAP primary
  (the surviving canonical row), keeping its ``doi``/``url``.
- Every other version's identifiers + OpenAlex locations are folded into the
  canonical row's ``locations`` JSON; the merge is recorded in ``provenance.dedup``.
- Each merged-away row becomes a ``status='r'`` tombstone carrying
  ``provenance.redirect.canonical_work_id`` so its identifiers still resolve and
  302-redirect to the canonical work (see ``works/utils/identifiers.py``).

Entry points:
- ``reconcile(work)`` — called whenever a work acquires/confirms an ``openalex_id``
  (harvest save, contribute-by-DOI, sweep). Merges its same-id siblings.
- ``sweep(queryset=None)`` — backfill ``locations`` on every work with an
  ``openalex_id`` (re-fetching the OpenAlex payload), then merge same-id groups.
  Used by the ``dedup_works`` command and the scheduled ``dedup_sweep`` task.
- ``unmerge(work)`` — re-promote a redirected row (correction path + tests).

Gated by ``settings.OPTIMAP_DEDUP_AUTO_MERGE`` (default True).
"""

import logging
from collections import defaultdict

from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from works.models import Work
from works.utils.doi import normalize_versioned_doi

logger = logging.getLogger(__name__)

# OpenAlex version vocabulary, ranked most→least authoritative for primary choice.
_VERSION_RANK = {"publishedVersion": 3, "acceptedVersion": 2, "submittedVersion": 1}


def _auto_merge_enabled() -> bool:
    return getattr(settings, "OPTIMAP_DEDUP_AUTO_MERGE", True)


def _norm_doi(doi) -> str | None:
    if not doi:
        return None
    d = doi.strip().lower()
    for prefix in ("https://doi.org/", "http://doi.org/", "doi.org/"):
        if d.startswith(prefix):
            d = d[len(prefix) :]
            break
    return d or None


def _location_matches_work(loc: dict, work) -> bool:
    """True if an OpenAlex location entry refers to the same copy as ``work``."""
    loc_doi = _norm_doi(loc.get("doi"))
    if loc_doi and loc_doi == _norm_doi(work.doi):
        return True
    landing = loc.get("landing_page_url")
    return bool(landing and work.url and landing == work.url)


def _work_version_rank(work, siblings_locations) -> int:
    """Rank a work by the OpenAlex version of the location matching its url/doi."""
    for loc in siblings_locations:
        if _location_matches_work(loc, work):
            return _VERSION_RANK.get(loc.get("version"), 0)
    return 0


def _all_locations(works) -> list[dict]:
    out = []
    for w in works:
        for loc in w.locations or []:
            if isinstance(loc, dict):
                out.append(loc)
    return out


def pick_primary(works):
    """Choose the canonical work among same-``openalex_id`` ``works``.

    Returns ``(primary, basis)`` where ``basis`` records why it was chosen:
    ``"openalex_primary_location"``, ``"version_rank"``, or ``"existing"``.
    """
    works = list(works)
    locations = _all_locations(works)

    # 1. The work matching OpenAlex's primary_location.
    primary_entry = next((loc for loc in locations if loc.get("is_primary")), None)
    if primary_entry is not None:
        for w in works:
            if _location_matches_work(primary_entry, w):
                return w, "openalex_primary_location"

    # 2. Highest version rank, tie-broken by earliest creation (stable canonical).
    ranked = sorted(works, key=lambda w: (-_work_version_rank(w, locations), w.id))
    if ranked and _work_version_rank(ranked[0], locations) > 0:
        return ranked[0], "version_rank"

    # 3. Fall back to the earliest-created row.
    return min(works, key=lambda w: w.id), "existing"


def _merge_locations(primary, others) -> list[dict]:
    """Fold others' locations into primary's, deduped by landing URL / pdf / doi."""
    merged = list(primary.locations or [])

    def key(loc):
        return loc.get("landing_page_url") or loc.get("pdf_url") or loc.get("doi")

    seen = {key(loc) for loc in merged if isinstance(loc, dict)}
    for other in others:
        for loc in other.locations or []:
            if not isinstance(loc, dict):
                continue
            k = key(loc)
            if k in seen:
                continue
            # A folded-in version is never the canonical's primary location.
            entry = dict(loc)
            entry["is_primary"] = bool(loc.get("is_primary")) and False
            entry["optimap_work_id"] = other.id
            merged.append(entry)
            seen.add(k)
    return merged


def _has_geometry(work) -> bool:
    return bool(work.geometry) and not work.geometry.empty


def _has_temporal(work) -> bool:
    return any(d is not None for d in (work.timeperiod_startdate or [])) or any(
        d is not None for d in (work.timeperiod_enddate or [])
    )


def _ensure_provenance(work) -> dict:
    return work.provenance if isinstance(work.provenance, dict) else {}


@transaction.atomic
def merge(primary, others, *, basis="openalex_id"):
    """Merge ``others`` into ``primary`` (canonical). Returns ``primary``.

    Keeps the primary's identifiers and (spatial/temporal) extent. Fills the
    primary's extent from an ``other`` only if the primary lacks it; records a
    ``provenance.dedup_conflict`` (audit only) when both carry differing extents.
    Each ``other`` becomes a ``status='r'`` tombstone pointing at ``primary``.
    """
    others = [o for o in others if o.id != primary.id]
    if not others:
        return primary

    now = timezone.now().isoformat()
    openalex_id = primary.openalex_id

    # Locations: fold everything onto the canonical row.
    primary.locations = _merge_locations(primary, others)

    # OpenAlex ids: fill any keys the primary is missing.
    primary_ids = dict(primary.openalex_ids or {})
    for other in others:
        for k, v in (other.openalex_ids or {}).items():
            primary_ids.setdefault(k, v)
    primary.openalex_ids = primary_ids

    prov = _ensure_provenance(primary)
    conflicts = list(prov.get("dedup_conflict") or [])
    merged_ids = []
    merged_identifiers = []

    for other in others:
        merged_ids.append(other.id)
        merged_identifiers.extend([x for x in (other.doi, other.url) if x])

        # Extent carry-over (lossless): only fill when the primary is empty.
        if not _has_geometry(primary) and _has_geometry(other):
            primary.geometry = other.geometry
        elif _has_geometry(primary) and _has_geometry(other) and not primary.geometry.equals(other.geometry):
            conflicts.append({"work_id": other.id, "kind": "geometry", "at": now})

        if not _has_temporal(primary) and _has_temporal(other):
            primary.timeperiod_startdate = other.timeperiod_startdate
            primary.timeperiod_enddate = other.timeperiod_enddate
        elif (
            _has_temporal(primary)
            and _has_temporal(other)
            and (
                (other.timeperiod_startdate or []) != (primary.timeperiod_startdate or [])
                or (other.timeperiod_enddate or []) != (primary.timeperiod_enddate or [])
            )
        ):
            conflicts.append({"work_id": other.id, "kind": "temporal", "at": now})

        # Turn the other row into a redirect tombstone.
        other_prov = _ensure_provenance(other)
        other_prov["redirect"] = {
            "canonical_work_id": primary.id,
            "canonical_identifier": primary.get_identifier(),
            "openalex_id": openalex_id,
            "at": now,
        }
        other_prov.setdefault("events", []).append({"type": "dedup_merge", "at": now, "canonical_work_id": primary.id})
        other.status = "r"
        other.provenance = other_prov
        other.save(update_fields=["status", "provenance", "lastUpdate"])

    prov["dedup"] = {
        "openalex_id": openalex_id,
        "merged_work_ids": merged_ids,
        "merged_identifiers": merged_identifiers,
        "method": basis,
        "primary_basis": getattr(primary, "_primary_basis", "existing"),
        "at": now,
    }
    if conflicts:
        prov["dedup_conflict"] = conflicts
    prov.setdefault("events", []).append({"type": "dedup_merge", "at": now, "merged_work_ids": merged_ids})
    primary.provenance = prov
    primary.save()

    logger.info(
        "Deduped openalex_id=%s: canonical work id=%s, redirected %s",
        openalex_id,
        primary.id,
        merged_ids,
    )
    return primary


def reconcile(work):
    """Merge ``work``'s same-``openalex_id`` siblings into one canonical row.

    No-op (returns the work unchanged) when auto-merge is disabled, the work has
    no ``openalex_id``, is itself a redirect tombstone, or has no live siblings.
    """
    if not _auto_merge_enabled():
        return work
    if not work.openalex_id or work.status == "r":
        return work

    siblings = list(Work.objects.filter(openalex_id=work.openalex_id).exclude(status="r"))
    if len(siblings) < 2:
        return work

    primary, basis = pick_primary(siblings)
    primary._primary_basis = basis
    others = [w for w in siblings if w.id != primary.id]
    return merge(primary, others)


# -----------------------------------------------------------------------------
# Version dedup — collapse ESSOAr/Authorea per-version DOIs onto one Work.
#
# ESS Open Archive mints a separate DOI per version of a preprint (``…/v2`` in
# the current era, a trailing ``.2`` in the legacy era), so a full harvest would
# create one Work per version and over-count the catalogue. This keeps the
# highest version as canonical and tombstones the older ones, reusing the same
# ``merge`` machinery as the openalex_id dedup above. Unlike that path it does
# not require an ``openalex_id`` — the DOI base is the join key.
# -----------------------------------------------------------------------------


def _pick_latest_version(works):
    """Canonical = highest version; tie-break by lowest id for a stable choice."""
    return max(works, key=lambda w: (normalize_versioned_doi(w.doi)[1] or 0, -w.id))


def _merge_version_group(works):
    """Merge a same-base ESSOAr version group onto its latest version.

    ``works`` may include the chosen primary — ``merge`` drops it from the
    others itself — so callers don't pre-filter.
    """
    primary = _pick_latest_version(works)
    primary._primary_basis = "doi_version"
    return merge(primary, works, basis="doi_version")


def _version_siblings(work):
    """Return ``(base, live_siblings)`` sharing ``work``'s versionless DOI base.

    ``live_siblings`` is empty when ``work`` is not a versioned ESSOAr DOI. The
    ``doi__startswith`` clause only narrows the DB scan; each candidate is
    re-normalized so a base that is a prefix of a *different* work id can't leak
    in (e.g. legacy ``essoar.10512157`` must not match ``essoar.105121570``).
    """
    base, version = normalize_versioned_doi(work.doi)
    if version is None:
        return base, []
    candidates = Work.objects.filter(doi__startswith=base).exclude(status="r")
    siblings = [w for w in candidates if normalize_versioned_doi(w.doi)[0] == base]
    return base, siblings


def reconcile_versions(work):
    """Collapse ``work``'s ESSOAr version siblings onto the latest-version Work.

    No-op when auto-merge is disabled, ``work`` is a tombstone, its DOI is not a
    versioned ESSOAr DOI, or it has no older/newer sibling. Returns the canonical
    Work (which may differ from ``work`` when a newer version wins).
    """
    if not _auto_merge_enabled() or work.status == "r":
        return work
    _base, siblings = _version_siblings(work)
    if len(siblings) < 2:
        return work
    return _merge_version_group(siblings)


#: DOI prefixes that carry versioned ESSOAr works (both eras). Anchored so the
#: sweep's filter can use the ``doi`` index instead of a leading-wildcard scan.
_ESSOAR_DOI_PREFIXES = ("10.22541/essoar.", "10.1002/essoar.")


def version_sweep(queryset=None, *, dry_run=False, limit=None, on_progress=None):
    """Collapse every ESSOAr version group in ``queryset`` onto its latest version.

    Backfill counterpart to :func:`reconcile_versions` for works already stored
    as separate versions. ``limit`` coarsely bounds the number of works scanned
    (a group split across the bound is simply picked up by the next sweep).
    Returns ``{groups_merged, works_redirected}``.
    """

    def report(message):
        (on_progress or logger.info)(message)

    if queryset is None:
        queryset = Work.objects.all()
    prefix_match = Q()
    for doi_prefix in _ESSOAR_DOI_PREFIXES:
        prefix_match |= Q(doi__startswith=doi_prefix)
    live = queryset.exclude(status="r").filter(prefix_match)
    if limit:
        live = live[:limit]

    groups: dict[str, list] = defaultdict(list)
    for work in live.iterator(chunk_size=200):
        base, version = normalize_versioned_doi(work.doi)
        if version is None:
            continue
        groups[base].append(work)

    stats = {"groups_merged": 0, "works_redirected": 0}
    prefix = "[dry-run] " if dry_run else ""
    for base, works in groups.items():
        if len(works) < 2:
            continue
        stats["groups_merged"] += 1
        stats["works_redirected"] += len(works) - 1
        if dry_run:
            report(f"{prefix}  {base}: would merge {len(works)} versions ({sorted(w.id for w in works)})")
            continue
        _merge_version_group(works)
    report(
        f"{prefix}Version sweep: {stats['groups_merged']} group(s) merged, "
        f"{stats['works_redirected']} older version(s) redirected."
    )
    return stats


def backfill_locations(work, *, matcher=None, force=False) -> bool:
    """Populate ``work.locations`` from OpenAlex. Returns True if it wrote anything.

    Re-fetches the OpenAlex payload (by ``openalex_id``, falling back to DOI),
    since the full payload was never stored. Fill-if-empty unless ``force``.
    """
    from works.harvesting.openalex_locations import build_locations
    from works.openalex_matcher import OPENALEX_API_BASE, get_openalex_matcher

    if not work.openalex_id:
        return False
    if work.locations and not force:
        return False

    matcher = matcher or get_openalex_matcher()
    payload = None
    wid = work.openalex_id.rsplit("/", 1)[-1]
    if wid:
        payload = matcher._make_request(f"{OPENALEX_API_BASE}/works/{wid}")
    if not payload and work.doi:
        payload = matcher.match_by_doi(work.doi)
    if not payload:
        return False

    locations = build_locations(payload)
    if not locations:
        return False
    work.locations = locations
    work.save(update_fields=["locations", "lastUpdate"])
    return True


def sweep(queryset=None, *, locations_only=False, force=False, dry_run=False, limit=None, on_progress=None):
    """Backfill locations on all works with an openalex_id, then merge groups.

    ``on_progress`` is an optional ``callable(str)`` for human-readable progress
    lines; the ``dedup_works`` command passes ``self.stdout.write`` to preserve
    interactive output. When ``None`` (e.g. the async ``dedup_sweep`` task)
    progress goes to the logger so it appears in the Django-Q worker log.

    Returns a stats dict: ``{locations_filled, groups_merged, works_redirected}``.
    """
    from works.openalex_matcher import get_openalex_matcher

    def report(message):
        if on_progress is not None:
            on_progress(message)
        else:
            logger.info(message)

    if queryset is None:
        queryset = Work.objects.all()
    base = queryset.exclude(status="r").exclude(openalex_id__isnull=True).exclude(openalex_id="")

    stats = {"locations_filled": 0, "groups_merged": 0, "works_redirected": 0}
    matcher = get_openalex_matcher()
    prefix = "[dry-run] " if dry_run else ""

    # Pass 1: backfill locations on every eligible work (one OpenAlex fetch each,
    # rate-limited — this is the slow pass, so report per-work + a running tally).
    to_fill = base if force else base.filter(locations=[])
    if limit:
        to_fill = to_fill[:limit]
    total = to_fill.count()
    report(f"{prefix}Pass 1/2: backfilling OpenAlex locations on {total} work(s)...")
    for i, work in enumerate(to_fill.iterator(chunk_size=50), start=1):
        if dry_run:
            stats["locations_filled"] += 1
            report(f"{prefix}  [{i}/{total}] work {work.id} ({work.openalex_id}) — would fetch locations")
            continue
        if backfill_locations(work, matcher=matcher, force=force):
            stats["locations_filled"] += 1
            report(f"{prefix}  [{i}/{total}] work {work.id} — locations filled ({stats['locations_filled']} so far)")
        else:
            report(f"{prefix}  [{i}/{total}] work {work.id} — no locations from OpenAlex")
    report(f"{prefix}Pass 1 done: {stats['locations_filled']} work(s) gained locations.")

    if locations_only:
        return stats

    # Pass 2: merge groups sharing an openalex_id.
    ids = list(base.values_list("openalex_id", flat=True).order_by("openalex_id").distinct())
    report(f"{prefix}Pass 2/2: scanning {len(ids)} OpenAlex id(s) for duplicate groups...")
    for openalex_id in ids:
        group = list(Work.objects.filter(openalex_id=openalex_id).exclude(status="r"))
        if len(group) < 2:
            continue
        if dry_run:
            stats["groups_merged"] += 1
            stats["works_redirected"] += len(group) - 1
            report(f"{prefix}  {openalex_id}: would merge {len(group)} works ({sorted(w.id for w in group)})")
            continue
        primary, basis = pick_primary(group)
        primary._primary_basis = basis
        others = [w for w in group if w.id != primary.id]
        merge(primary, others)
        stats["groups_merged"] += 1
        stats["works_redirected"] += len(others)
        report(
            f"  {openalex_id}: merged {len(others)} into canonical work {primary.id} "
            f"(basis={basis}); redirected {sorted(w.id for w in others)}"
        )
    report(
        f"{prefix}Pass 2 done: {stats['groups_merged']} group(s) merged, "
        f"{stats['works_redirected']} work(s) redirected."
    )

    # Pass 3: collapse ESSOAr/Authorea version siblings (independent of openalex_id).
    report(f"{prefix}Pass 3/3: scanning ESSOAr version groups...")
    version_stats = version_sweep(queryset, dry_run=dry_run, limit=limit, on_progress=report)
    stats["groups_merged"] += version_stats["groups_merged"]
    stats["works_redirected"] += version_stats["works_redirected"]

    return stats


@transaction.atomic
def unmerge(work):
    """Re-promote a redirected tombstone back to a standalone work.

    Restores ``status`` to a sensible value (Harvested), clears the redirect
    pointer, and drops the work from the canonical's ``provenance.dedup`` list.
    Returns the re-promoted work.
    """
    if work.status != "r":
        return work
    prov = _ensure_provenance(work)
    redirect = prov.pop("redirect", None)
    now = timezone.now().isoformat()
    prov.setdefault("events", []).append({"type": "dedup_unmerge", "at": now})
    work.provenance = prov
    work.status = "h"
    work.save(update_fields=["status", "provenance", "lastUpdate"])

    if redirect and redirect.get("canonical_work_id"):
        canonical = Work.objects.filter(id=redirect["canonical_work_id"]).first()
        if canonical is not None:
            cprov = _ensure_provenance(canonical)
            dedup = cprov.get("dedup")
            if isinstance(dedup, dict):
                dedup["merged_work_ids"] = [i for i in dedup.get("merged_work_ids", []) if i != work.id]
                canonical.provenance = cprov
                canonical.save(update_fields=["provenance", "lastUpdate"])
    return work
