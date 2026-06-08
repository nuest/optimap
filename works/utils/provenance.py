# SPDX-FileCopyrightText: 2026 OPTIMETA and KOMET projects
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Helpers for the structured ``Work.provenance`` JSON.

Schema:
    {
        "harvest": {
            "harvester": "harvest_oai_endpoint",
            "source_url": "https://...",
            "source_type": "oai-pmh",
            "harvested_at": "2026-04-30T12:00:00+00:00",
            "original_record": {...},   # source-specific raw record (optional)
        },
        "metadata_sources": {            # per-field origin
            "authors": "openalex" | "original_source",
            "geometry": "DC.SpatialCoverage",
            ...
        },
        "openalex_match": {
            "status": "verified" | "unverified" | "none",
            "score": 0.92,
            "matched_id": "https://openalex.org/W123",
            "top_candidate": {...}        # only when unverified
        },
        "events": [                       # chronological audit log
            {"type": "contribution", "user_id": 42, "kind": "spatial",
             "at": "2026-04-30T...", "changes": [...]},
            {"type": "publish", "user_id": 1, "at": "..."},
            {"type": "unpublish", "user_id": 1, "at": "..."}
        ],
    }

All keys are optional; fresh Works start with ``{}``.

Public subset (returned to unauthenticated callers and non-curator users):
  - ``harvest.original_record`` is removed (raw upstream payload)
  - ``openalex_match.top_candidate`` is removed (verbose raw API response)
  - ``user_id`` is removed from every event (personal data)
"""

import copy

from django.utils import timezone


def public_subset(provenance) -> dict:
    """Return a privacy-safe copy of ``provenance`` suitable for anonymous API responses.

    Strips: ``harvest.original_record``, ``openalex_match.top_candidate``,
    and ``user_id`` from every event.
    """
    if not isinstance(provenance, dict):
        return {}
    result = copy.deepcopy(provenance)

    harvest = result.get("harvest")
    if isinstance(harvest, dict):
        harvest.pop("original_record", None)

    openalex = result.get("openalex_match")
    if isinstance(openalex, dict):
        openalex.pop("top_candidate", None)

    events = result.get("events")
    if isinstance(events, list):
        for ev in events:
            if isinstance(ev, dict):
                ev.pop("user_id", None)

    return result


def _ensure_dict(value):
    """Tolerate None or unexpected values in the provenance field."""
    if isinstance(value, dict):
        return value
    return {}


def append_event(work, event_type, **fields):
    """Append a structured event to ``work.provenance['events']`` and save the field.

    Caller is responsible for any other field changes; this helper only touches provenance.
    """
    provenance = _ensure_dict(work.provenance)
    event = {
        "type": event_type,
        "at": timezone.now().isoformat(),
    }
    event.update({k: v for k, v in fields.items() if v is not None})
    provenance.setdefault("events", []).append(event)
    work.provenance = provenance


def user_has_contributed_kind(work, user_id, kind) -> bool:
    """True if ``user_id`` has already contributed ``kind`` to ``work``.

    Source of truth is the provenance event log — survives both account
    deletion (Contribution.user goes NULL) and Recognition Board row
    deletion. Used by the contribution endpoints to dedupe Recognition
    Board counters: same user repeatedly editing the same property type
    on the same work counts once. Different users editing the same
    property each count once.

    Call this *before* ``append_event`` so the event being recorded now
    is not in the log yet.
    """
    if user_id is None or kind is None:
        return False
    provenance = _ensure_dict(work.provenance)
    for evt in provenance.get("events", []) or []:
        if evt.get("type") != "contribution":
            continue
        if evt.get("user_id") != user_id:
            continue
        if kind in (evt.get("kinds") or []):
            return True
    return False
