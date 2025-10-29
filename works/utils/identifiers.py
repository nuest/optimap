"""
Utility functions for resolving work identifiers.

This module provides centralized logic for resolving various identifier types
(DOI, internal ID, handle) to Work objects.
"""

import logging
from urllib.parse import unquote
from django.http import Http404
from works.models import Work

logger = logging.getLogger(__name__)


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
    if '/' in identifier or identifier.startswith('10.'):
        try:
            work = Work.objects.get(doi=identifier)
            identifier_type = 'doi'
            logger.debug(f"Found work by DOI: {identifier}")
        except Work.DoesNotExist:
            logger.debug(f"No work found with DOI: {identifier}")

    # Strategy 2: Try internal ID if identifier is numeric
    if work is None and identifier.isdigit():
        try:
            work = Work.objects.get(id=int(identifier))
            identifier_type = 'id'
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
