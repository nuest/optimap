# SPDX-FileCopyrightText: 2025 OPTIMETA and KOMET projects <https://projects.tib.eu/komet>
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Utility functions for resolving work identifiers.

This module provides centralized logic for resolving various identifier types
(DOI, internal ID, handle) to Work objects.
"""

import logging
import re
from urllib.parse import unquote

from django.http import Http404

from works.models import Work

logger = logging.getLogger(__name__)

# Crossref's recommended DOI pattern (https://www.crossref.org/blog/dois-and-matching-regular-expressions/),
# applied after stripping any resolver prefix. Case-insensitive on the "10." literal.
_DOI_RE = re.compile(r"^10\.\d{4,9}/\S+$", re.IGNORECASE)

# Resolver / scheme prefixes that may wrap a bare DOI, longest first so the most
# specific match wins. Comparison is case-insensitive; the DOI body keeps its case
# because stored Crossref DOIs are case-preserving.
_DOI_PREFIXES = (
    "https://dx.doi.org/",
    "http://dx.doi.org/",
    "https://doi.org/",
    "http://doi.org/",
    "dx.doi.org/",
    "doi.org/",
    "doi:",
)


def normalize_doi(raw):
    """Normalize a user-supplied DOI or DOI URL to a bare DOI string.

    Strips surrounding whitespace and any known resolver/scheme prefix, then
    validates the remainder against the DOI shape. Returns the bare DOI, or
    ``None`` if the input is empty or not a DOI.

    The DOI body's case is preserved (DOIs are case-insensitive per spec, but
    stored Crossref DOIs keep their original case); callers that compare against
    the database should use ``doi__iexact``.
    """
    if not raw:
        return None
    doi = raw.strip()
    if not doi:
        return None
    lowered = doi.lower()
    for prefix in _DOI_PREFIXES:
        if lowered.startswith(prefix):
            doi = doi[len(prefix) :]
            break
    doi = doi.strip()
    if not _DOI_RE.match(doi):
        return None
    return doi


def resolve_work_identifier(identifier):
    """
    Resolve a work identifier to a Work object.

    Tries to resolve the identifier in this order:
    1. DOI (if identifier contains '/' or starts with '10.')
    2. Internal database ID (if identifier is numeric)
    3. Handle (placeholder for future implementation)

    Args:
        identifier (str): The identifier to resolve (DOI, ID, or future handle)

    Returns:
        tuple: (work, identifier_type) where:
            - work: Work object or None if not found
            - identifier_type: 'doi', 'id', 'handle', or None

    Raises:
        Http404: If no work is found with the given identifier

    Example:
        >>> work, id_type = resolve_work_identifier("10.1234/example")
        >>> print(f"Found {work.title} via {id_type}")
        Found Example Work via doi

        >>> work, id_type = resolve_work_identifier("123")
        >>> print(f"Found {work.title} via {id_type}")
        Found Example Work via id
    """
    matched, identifier_type = _match_work(identifier)
    if matched is None:
        logger.warning(f"Work not found with identifier: {identifier}")
        raise Http404("Work not found.")
    # Follow a redirect tombstone (merged duplicate) to the canonical work so
    # all callers operate on the surviving row.
    return matched.canonical_work(), identifier_type


def _match_work(identifier):
    """Look up the ``Work`` row an identifier refers to (may be a redirect tombstone).

    Returns ``(work, identifier_type)`` or ``(None, None)``. Resolution order:
    DOI, internal ID, OpenAlex id (full/bare), OpenAlex external ids
    (``openalex_ids`` — doi/pmid/pmcid/mag), then OpenAlex location landing-page
    URL / version DOI (``locations``). The later strategies make every known
    identifier of a merged work resolve to its canonical row.
    """
    identifier = unquote(identifier)
    work = None

    # Strategy 1: DOI (contains '/' or starts with '10.')
    if "/" in identifier or identifier.startswith("10."):
        work = Work.objects.filter(doi=identifier).first()
        if work is not None:
            return work, "doi"

    # Strategy 2: internal ID
    if identifier.isdigit():
        work = Work.objects.filter(id=int(identifier)).first()
        if work is not None:
            return work, "id"

    # Strategy 3: OpenAlex work id (accept full URL or bare W-id).
    oa = identifier
    if oa.lower().startswith(("w",)) or "openalex.org/" in oa.lower():
        bare = oa.rsplit("/", 1)[-1]
        work = Work.objects.filter(openalex_id__iendswith=bare).first()
        if work is not None:
            return work, "openalex_id"

    # Strategy 4: external ids carried in openalex_ids (pmid/pmcid/mag/doi).
    for key in ("pmid", "pmcid", "mag", "doi"):
        work = Work.objects.filter(**{f"openalex_ids__{key}": identifier}).first()
        if work is not None:
            return work, "openalex_external_id"

    # Strategy 5: an OpenAlex location landing-page URL or version DOI.
    work = Work.objects.filter(locations__contains=[{"landing_page_url": identifier}]).first()
    if work is None:
        work = Work.objects.filter(locations__contains=[{"doi": identifier}]).first()
    if work is not None:
        return work, "location"

    return None, None


def resolve_work_for_landing(identifier):
    """Resolve for the landing page, signalling when a 302 to canonical is needed.

    Returns ``(canonical_work, identifier_type, should_redirect)``. ``should_redirect``
    is True when the requested identifier matched a *different* row than the
    canonical one (a merged-away duplicate or an alternate identifier of one) —
    the landing view 302-redirects to ``/work/<canonical>`` in that case.
    """
    matched, identifier_type = _match_work(identifier)
    if matched is None:
        logger.warning(f"Work not found with identifier: {identifier}")
        raise Http404("Work not found.")
    canonical = matched.canonical_work()
    return canonical, identifier_type, canonical.id != matched.id


def get_work_by_identifier(identifier):
    """
    Convenience function to get a Work object by identifier.

    Args:
        identifier (str): The identifier to resolve

    Returns:
        Work: The Work object

    Raises:
        Http404: If no work is found with the given identifier
    """
    work, _ = resolve_work_identifier(identifier)
    return work
