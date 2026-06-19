# SPDX-FileCopyrightText: 2026 OPTIMETA and KOMET projects <https://projects.tib.eu/komet>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Shared conflict-resolution helper for metadata enrichment sources.

OPTIMAP enriches harvested works from external sources (OpenAlex, OpenAIRE).
The agreed policy is **fill-if-empty**: an enrichment source may only populate a
field that is currently empty; it never overwrites a value already supplied by
the original source / harvest origin or by an earlier enrichment source. Every
decision — both the fills and the offers that were rejected because a value
already existed — is recorded in ``Work.provenance`` so the resolution is fully
auditable.

``apply_enrichment`` is source-agnostic; callers pass a ``candidates`` dict of
``{work_field: value}`` and a ``source_name`` (e.g. ``"openaire"``). It mutates
the work in memory and records ``provenance.metadata_sources`` but does **not**
save — the caller decides when/what to persist and is responsible for appending
the corresponding ``provenance.events`` entry.
"""


def _is_blank(value) -> bool:
    """True when ``value`` carries no information worth keeping.

    Stricter than ``works.harvesting.common._is_empty_for_update``: it also
    treats empty / whitespace-only strings as blank, matching how the
    abstract-less backfill queryset selects works (``abstract=""`` or NULL).
    """
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip() == ""
    if isinstance(value, (list, tuple)):
        return len(value) == 0
    if hasattr(value, "empty"):
        return bool(getattr(value, "empty"))
    return False


def apply_enrichment(work, candidates, source_name):
    """Apply the fill-if-empty enrichment policy to ``work`` from ``candidates``.

    Args:
        work: a ``Work`` instance (mutated in memory, not saved).
        candidates: ``{field_name: value}`` offered by the enrichment source.
        source_name: provenance label for the source, e.g. ``"openaire"``.

    Returns:
        ``(fields_filled, fields_offered_not_applied)`` — lists of field names.
        ``fields_filled`` were empty and have now been set (and attributed in
        ``provenance.metadata_sources``); ``fields_offered_not_applied`` had a
        non-empty candidate value but the work already had a value, so the
        existing value was kept (the documented conflict outcome).
    """
    fields_filled = []
    fields_offered_not_applied = []

    provenance = work.provenance if isinstance(work.provenance, dict) else {}
    metadata_sources = provenance.setdefault("metadata_sources", {})

    for field, value in candidates.items():
        if _is_blank(value):
            continue  # source offered nothing for this field
        if _is_blank(getattr(work, field, None)):
            setattr(work, field, value)
            metadata_sources[field] = source_name
            fields_filled.append(field)
        else:
            fields_offered_not_applied.append(field)

    work.provenance = provenance
    return fields_filled, fields_offered_not_applied
