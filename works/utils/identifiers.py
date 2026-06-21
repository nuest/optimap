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
    # Decode URL-encoded identifier
    identifier = unquote(identifier)

    work = None
    identifier_type = None

    # Strategy 1: Try DOI first (contains '/' or starts with '10.')
    if "/" in identifier or identifier.startswith("10."):
        try:
            work = Work.objects.get(doi=identifier)
            identifier_type = "doi"
            logger.debug(f"Found work by DOI: {identifier}")
        except Work.DoesNotExist:
            logger.debug(f"No work found with DOI: {identifier}")

    # Strategy 2: Try internal ID if identifier is numeric
    if work is None and identifier.isdigit():
        try:
            work = Work.objects.get(id=int(identifier))
            identifier_type = "id"
            logger.debug(f"Found work by ID: {identifier}")
        except Work.DoesNotExist:
            logger.debug(f"No work found with ID: {identifier}")

    # Strategy 3: Try Handle (placeholder for future implementation)
    # Future: if work is None and identifier.startswith('hdl:'):
    #     try:
    #         handle = identifier.replace('hdl:', '')
    #         work = Work.objects.get(handle=handle)
    #         identifier_type = 'handle'
    #         logger.debug(f"Found work by handle: {identifier}")
    #     except Work.DoesNotExist:
    #         logger.debug(f"No work found with handle: {identifier}")

    # If still not found, raise 404
    if work is None:
        logger.warning(f"Work not found with identifier: {identifier}")
        raise Http404("Work not found.")

    return work, identifier_type


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
