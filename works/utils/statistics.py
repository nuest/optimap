# publications/utils/statistics.py
"""
Statistics utilities for OPTIMAP publications.
Provides cached statistics about the work database.
"""

from django.core.cache import cache
from django.db.models import Count, Q
from works.models import Work


STATS_CACHE_KEY = 'publications_statistics'
STATS_CACHE_TIMEOUT = 86400  # 24 hours in seconds


def calculate_statistics():
    """
    Calculate comprehensive statistics about publications.

    Returns:
        dict: Statistics including total count, published count,
              counts with geometry, temporal data, authors, etc.
    """
    # Base queryset for published works
    published = Work.objects.filter(status='p')

    stats = {
        'total_works': Work.objects.count(),
        'published_works': published.count(),
        'with_geometry': published.exclude(geometry__isnull=True).count(),
        'with_temporal': published.filter(
            Q(timeperiod_startdate__isnull=False) |
            Q(timeperiod_enddate__isnull=False)
        ).count(),
        'with_authors': published.exclude(authors__isnull=True).exclude(authors=[]).count(),
        'with_doi': published.exclude(doi__isnull=True).exclude(doi='').count(),
        'with_abstract': published.exclude(abstract__isnull=True).exclude(abstract='').count(),
        'open_access': published.exclude(
            openalex_open_access_status__isnull=True
        ).exclude(
            openalex_open_access_status=''
        ).count(),
        'from_openalex': published.exclude(
            openalex_id__isnull=True
        ).exclude(
            openalex_id=''
        ).count(),
    }

    # Calculate percentage with complete metadata (geometry + temporal + authors)
    complete = published.exclude(geometry__isnull=True).filter(
        Q(timeperiod_startdate__isnull=False) | Q(timeperiod_enddate__isnull=False)
    ).exclude(authors__isnull=True).exclude(authors=[])
    stats['with_complete_metadata'] = complete.count()

    # Calculate percentage
    if stats['published_works'] > 0:
        stats['complete_percentage'] = round(
            (stats['with_complete_metadata'] / stats['published_works']) * 100, 1
        )
    else:
        stats['complete_percentage'] = 0

    return stats


def get_cached_statistics():
    """
    Get statistics from cache or calculate if not cached.

    Returns:
        dict: Cached or freshly calculated statistics
    """
    stats = cache.get(STATS_CACHE_KEY)

    if stats is None:
        stats = calculate_statistics()
        cache.set(STATS_CACHE_KEY, stats, STATS_CACHE_TIMEOUT)

    return stats


def update_statistics_cache():
    """
    Force recalculation and update of statistics cache.
    Called by management command for nightly updates.

    Returns:
        dict: The updated statistics
    """
    stats = calculate_statistics()
    cache.set(STATS_CACHE_KEY, stats, STATS_CACHE_TIMEOUT)
    return stats


def clear_statistics_cache():
    """
    Clear the statistics cache.
    Useful when publications are added/removed/updated.
    """
    cache.delete(STATS_CACHE_KEY)
