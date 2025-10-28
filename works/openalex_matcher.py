"""
OpenAlex matching service for publications.

This module provides centralized OpenAlex work matching functionality
that can be used across all harvesting workflows (OAI-PMH, RSS, etc).
"""

import logging
import requests
import time
from typing import Dict, Optional, List, Tuple
from urllib.parse import quote

logger = logging.getLogger(__name__)

OPENALEX_API_BASE = "https://api.openalex.org"
REQUEST_DELAY = 0.1  # 100ms delay between requests to be polite


class OpenAlexMatcher:
    """
    Centralized service for matching publications to OpenAlex works.

    Implements multiple matching strategies with fallback:
    1. DOI-based exact match
    2. Title + first author match
    3. Title-only match (partial)
    """

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'OPTIMAP/1.0 (mailto:login@optimap.science)',
            'Accept': 'application/json'
        })
        self.last_request_time = 0

    def _rate_limit(self):
        """Implement polite rate limiting."""
        elapsed = time.time() - self.last_request_time
        if elapsed < REQUEST_DELAY:
            time.sleep(REQUEST_DELAY - elapsed)
        self.last_request_time = time.time()

    def _make_request(self, url: str, params: Optional[Dict] = None) -> Optional[Dict]:
        """Make a rate-limited request to OpenAlex API."""
        self._rate_limit()
        try:
            response = self.session.get(url, params=params, timeout=10)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            logger.warning("OpenAlex API request failed: %s", str(e))
            return None

    def match_by_doi(self, doi: str) -> Optional[Dict]:
        """
        Exact match by DOI.

        Args:
            doi: The DOI string (e.g., "10.1234/example")

        Returns:
            OpenAlex work data if found, None otherwise
        """
        if not doi:
            return None

        # Clean DOI
        doi = doi.strip().lower()
        if doi.startswith('http'):
            doi = doi.split('doi.org/')[-1]

        url = f"{OPENALEX_API_BASE}/works/doi:{quote(doi)}"
        logger.debug("Matching by DOI: %s", doi)

        data = self._make_request(url)
        if data and data.get('id'):
            logger.info("Found OpenAlex match by DOI: %s -> %s", doi, data['id'])
            return data

        return None

    def match_by_title_author(self, title: str, author: Optional[str] = None) -> Tuple[Optional[Dict], List[Dict]]:
        """
        Match by title and optionally first author.

        Args:
            title: Work title
            author: First author name (optional)

        Returns:
            Tuple of (exact_match, partial_matches)
            - exact_match: Single best match if confidence is high
            - partial_matches: List of potential matches with metadata
        """
        if not title:
            return None, []

        # Build search filter
        filter_parts = [f'title.search:{quote(title)}']
        if author:
            filter_parts.append(f'author.search:{quote(author)}')

        filter_str = ','.join(filter_parts)
        url = f"{OPENALEX_API_BASE}/works"
        params = {
            'filter': filter_str,
            'per-page': 5  # Get top 5 matches
        }

        logger.debug("Matching by title%s: %s", " + author" if author else "", title[:50])

        data = self._make_request(url, params)
        if not data or not data.get('results'):
            return None, []

        results = data['results']
        partial_matches = []

        for result in results:
            match_info = {
                'openalex_id': result.get('id'),
                'title': result.get('title'),
                'doi': result.get('doi'),
                'match_type': 'title+author' if author else 'title',
                'authors': [a.get('author', {}).get('display_name') for a in result.get('authorships', [])[:3]]
            }
            partial_matches.append(match_info)

        # If we have a very close title match with author, consider it exact
        if results and author:
            best_match = results[0]
            # Check if title is very similar (simple heuristic)
            if self._titles_similar(title, best_match.get('title', '')):
                logger.info("Found strong OpenAlex match by title+author: %s", best_match['id'])
                return best_match, partial_matches

        logger.info("Found %d partial OpenAlex matches for title: %s", len(partial_matches), title[:50])
        return None, partial_matches

    def _titles_similar(self, title1: str, title2: str, threshold: float = 0.9) -> bool:
        """
        Simple title similarity check.

        Uses character overlap ratio as a basic similarity metric.
        """
        t1 = title1.lower().strip()
        t2 = title2.lower().strip()

        if not t1 or not t2:
            return False

        # Exact match
        if t1 == t2:
            return True

        # Character-level overlap
        set1 = set(t1)
        set2 = set(t2)
        overlap = len(set1 & set2)
        total = max(len(set1), len(set2))

        similarity = overlap / total if total > 0 else 0
        return similarity >= threshold

    def extract_openalex_fields(self, work_data: Dict) -> Dict:
        """
        Extract relevant fields from OpenAlex work data.

        Args:
            work_data: Full OpenAlex work response

        Returns:
            Dictionary with extracted fields for Work model
        """
        # Safely extract fulltext origin
        fulltext_origin = None
        primary_location = work_data.get('primary_location')
        if primary_location and isinstance(primary_location, dict):
            source = primary_location.get('source')
            if source and isinstance(source, dict):
                fulltext_origin = source.get('type')

        extracted = {
            'openalex_id': work_data.get('id'),
            'openalex_fulltext_origin': fulltext_origin,
            'openalex_is_retracted': work_data.get('is_retracted', False),
            'openalex_ids': work_data.get('ids', {}),
            'type': work_data.get('type'),  # OpenAlex work type
            'keywords': [],
            'openalex_open_access_status': None,
            'topics': [],
            'authors': []
        }

        # Extract authors (display_name from authorships)
        authorships = work_data.get('authorships', [])
        if authorships:
            authors = []
            for authorship in authorships:
                author = authorship.get('author', {})
                if author and author.get('display_name'):
                    authors.append(author.get('display_name'))
            extracted['authors'] = authors

        # Extract keywords (display_name only)
        keywords = work_data.get('keywords', [])
        if keywords:
            extracted['keywords'] = [kw.get('display_name') for kw in keywords if kw.get('display_name')]

        # Extract open access status
        open_access = work_data.get('open_access', {})
        if open_access.get('is_oa'):
            extracted['openalex_open_access_status'] = open_access.get('oa_status')
        else:
            extracted['openalex_open_access_status'] = None

        # Extract topics (display_name only)
        topics = work_data.get('topics', [])
        if topics:
            extracted['topics'] = [topic.get('display_name') for topic in topics if topic.get('display_name')]

        return extracted

    def match_publication(
        self,
        title: str,
        doi: Optional[str] = None,
        author: Optional[str] = None
    ) -> Tuple[Optional[Dict], Optional[List[Dict]]]:
        """
        Main entry point for matching a work.

        Tries multiple strategies in order:
        1. DOI match (if DOI provided)
        2. Title + author match (if author provided)
        3. Title-only match

        Args:
            title: Work title (required)
            doi: DOI if available
            author: First author name if available

        Returns:
            Tuple of (exact_match_fields, partial_matches)
            - exact_match_fields: Dict with OpenAlex fields if perfect match found, None otherwise
            - partial_matches: List of potential matches with metadata
        """
        # Strategy 1: DOI match
        if doi:
            work_data = self.match_by_doi(doi)
            if work_data:
                fields = self.extract_openalex_fields(work_data)
                match_info = [{
                    'openalex_id': work_data.get('id'),
                    'title': work_data.get('title'),
                    'doi': work_data.get('doi'),
                    'match_type': 'doi',
                    'matched': True
                }]
                return fields, match_info

        # Strategy 2 & 3: Title-based matching
        exact_match, partial_matches = self.match_by_title_author(title, author)

        if exact_match:
            fields = self.extract_openalex_fields(exact_match)
            return fields, partial_matches

        # No exact match, return partial matches
        return None, partial_matches if partial_matches else None


# Singleton instance
_matcher = None


def get_openalex_matcher() -> OpenAlexMatcher:
    """Get or create the singleton OpenAlexMatcher instance."""
    global _matcher
    if _matcher is None:
        _matcher = OpenAlexMatcher()
    return _matcher
