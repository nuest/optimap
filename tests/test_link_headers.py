# SPDX-FileCopyrightText: 2026 OPTIMETA and KOMET projects <https://projects.tib.eu/komet>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests for RFC 5988 Link headers emitted by LinkHeaderPagination."""

from django.test import TestCase
from django.contrib.auth import get_user_model
from works.models import Work

User = get_user_model()

WORKS_URL = '/api/v1/works/'


def _parse_link_header(header):
    """Return a dict mapping rel to url from a Link header value."""
    result = {}
    for part in header.split(','):
        part = part.strip()
        if not part:
            continue
        url_part, *params = [p.strip() for p in part.split(';')]
        url = url_part.strip('<>')
        for param in params:
            if param.startswith('rel='):
                rel = param.split('=', 1)[1].strip('"')
                result[rel] = url
    return result


def _make_works(n, status='p'):
    for i in range(n):
        Work.objects.create(title=f'Work {i}', status=status)


class LinkHeaderSinglePageTests(TestCase):
    """When all results fit on one page there is no next/prev but first/last exist."""

    def setUp(self):
        _make_works(3)

    def tearDown(self):
        Work.objects.all().delete()

    def test_link_header_present(self):
        resp = self.client.get(WORKS_URL + '?limit=10')
        self.assertIn('Link', resp)

    def test_no_next_or_prev_on_single_page(self):
        resp = self.client.get(WORKS_URL + '?limit=10')
        links = _parse_link_header(resp['Link'])
        self.assertNotIn('next', links)
        self.assertNotIn('prev', links)

    def test_first_and_last_both_point_to_offset_zero(self):
        resp = self.client.get(WORKS_URL + '?limit=10')
        links = _parse_link_header(resp['Link'])
        self.assertIn('first', links)
        self.assertIn('last', links)
        self.assertIn('offset=0', links['first'])
        self.assertIn('offset=0', links['last'])


class LinkHeaderMultiPageTests(TestCase):
    """Multi-page result sets produce next/prev/first/last correctly."""

    def setUp(self):
        _make_works(10)

    def tearDown(self):
        Work.objects.all().delete()

    def _links(self, url):
        resp = self.client.get(url)
        self.assertIn('Link', resp)
        return _parse_link_header(resp['Link'])

    def test_first_page_has_next_but_no_prev(self):
        links = self._links(WORKS_URL + '?limit=3&offset=0')
        self.assertIn('next', links)
        self.assertNotIn('prev', links)

    def test_last_page_has_prev_but_no_next(self):
        links = self._links(WORKS_URL + '?limit=3&offset=9')
        self.assertIn('prev', links)
        self.assertNotIn('next', links)

    def test_middle_page_has_both_next_and_prev(self):
        links = self._links(WORKS_URL + '?limit=3&offset=3')
        self.assertIn('next', links)
        self.assertIn('prev', links)

    def test_first_link_always_offset_zero(self):
        for offset in (0, 3, 9):
            links = self._links(f'{WORKS_URL}?limit=3&offset={offset}')
            self.assertIn('offset=0', links['first'],
                          f'first link wrong at offset={offset}')

    def test_last_link_offset_matches_final_page(self):
        # 10 works, limit=3 → pages at 0,3,6,9; last page starts at 9
        # Formula: (max(0, count-1) // limit) * limit = (9 // 3) * 3 = 9
        links = self._links(WORKS_URL + '?limit=3&offset=0')
        self.assertIn('offset=9', links['last'])

    def test_last_link_exact_multiple(self):
        # 9 works, limit=3 → pages at 0,3,6; last page starts at 6
        Work.objects.last().delete()  # drop to 9 works
        links = self._links(WORKS_URL + '?limit=3&offset=0')
        self.assertIn('offset=6', links['last'])

    def test_next_link_advances_by_limit(self):
        links = self._links(WORKS_URL + '?limit=3&offset=0')
        self.assertIn('offset=3', links['next'])

    def test_prev_link_retreats_by_limit(self):
        links = self._links(WORKS_URL + '?limit=3&offset=6')
        self.assertIn('offset=3', links['prev'])


class LinkHeaderQueryParamPreservationTests(TestCase):
    """first/last/next/prev must preserve extra query params like minimal=true."""

    def setUp(self):
        _make_works(5)

    def tearDown(self):
        Work.objects.all().delete()

    def test_extra_params_preserved_in_all_rels(self):
        resp = self.client.get(WORKS_URL + '?limit=2&offset=0&minimal=true')
        self.assertIn('Link', resp)
        links = _parse_link_header(resp['Link'])
        for rel in ('next', 'first', 'last'):
            self.assertIn('minimal=true', links[rel],
                          f'minimal=true missing from {rel} link: {links[rel]}')

    def test_limit_preserved_in_first_and_last(self):
        resp = self.client.get(WORKS_URL + '?limit=2&offset=2')
        links = _parse_link_header(resp['Link'])
        self.assertIn('limit=2', links['first'])
        self.assertIn('limit=2', links['last'])


class LinkHeaderStatisticsTests(TestCase):
    """Statistics endpoint is a ViewSet (not paginated) — no Link header."""

    def test_statistics_has_no_link_header(self):
        resp = self.client.get('/api/v1/statistics/')
        self.assertNotIn('Link', resp)

    def test_statistics_appears_in_api_root(self):
        resp = self.client.get('/api/v1/')
        self.assertIn('statistics', resp.json())
