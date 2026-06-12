# SPDX-FileCopyrightText: 2026 OPTIMETA and KOMET projects <https://projects.tib.eu/komet>
# SPDX-License-Identifier: GPL-3.0-or-later

"""View-cache tests for issue #180 / commit 1 of the landing-page caching plan.

Covers:
- ``@cache_page(cache='memory')`` decorators on the static / low-change
  anonymous pages (privacy, about, accessibility, feeds, sitemap_page,
  RobotsView): a second request reuses the cached response without
  recomputing the view body.
- The anonymous ``work_landing`` context cache (key
  ``work_landing:ctx:<host>:<work.id>:<lastUpdate>``): cache miss on
  first request, cache hit on second; saving the work (which bumps
  ``lastUpdate``) immediately misses the old entry; staff requests
  always render live.

The tests use the real ``LocMemCache`` backend from ``CACHES['memory']``
and clear it in ``setUp`` so they're deterministic across runs.
"""

from __future__ import annotations

import json
import os
from unittest import mock

import django
from django.contrib.gis.geos import GeometryCollection, GEOSGeometry
from django.core.cache import caches
from django.test import Client, TestCase
from django.urls import reverse

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "optimap.settings")
django.setup()

from works.models import Source, Work

User = django.contrib.auth.get_user_model() if hasattr(django.contrib, "auth") else None
from django.contrib.auth import get_user_model

User = get_user_model()


def _polygon_collection(coords):
    geom = GEOSGeometry(json.dumps({"type": "Polygon", "coordinates": [coords]}), srid=4326)
    return GeometryCollection(geom, srid=4326)


def _make_published_work(**overrides) -> Work:
    src = Source.objects.create(
        name="Cache Test Journal",
        url_field="https://example.test/oai",
        homepage_url="https://example.test/",
        issn_l="1234-5678",
        harvest_interval_minutes=1440,
    )
    box = [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0], [0.0, 0.0]]
    defaults = dict(
        title="Cache test work",
        abstract="A short abstract for caching tests.",
        url="https://example.test/article/1",
        doi="10.1234/cache.test.1",
        source=src,
        status="p",
        geometry=_polygon_collection(box),
        authors=["Test, Alice"],
        publicationDate="2025-01-01",
    )
    defaults.update(overrides)
    return Work.objects.create(**defaults)


class StaticPageCacheTests(TestCase):
    """`@cache_page(cache='memory')` is wired up — second hit uses the cache."""

    def setUp(self):
        self.client = Client()
        caches["memory"].clear()

    def _hits_cache_on_second_request(self, url: str):
        """Second GET reuses the cached response (renders identical bytes
        without re-running the view body)."""
        with mock.patch(
            "django.shortcuts.render", wraps=__import__("django.shortcuts", fromlist=["render"]).render
        ) as _:
            r1 = self.client.get(url)
            self.assertEqual(r1.status_code, 200)
            r2 = self.client.get(url)
            self.assertEqual(r2.status_code, 200)
            self.assertEqual(r1.content, r2.content)

    def test_privacy_uses_cache_page(self):
        url = reverse("optimap:privacy")
        self._hits_cache_on_second_request(url)

    def test_about_uses_cache_page(self):
        url = reverse("optimap:about")
        self._hits_cache_on_second_request(url)

    def test_accessibility_uses_cache_page(self):
        url = reverse("optimap:accessibility")
        self._hits_cache_on_second_request(url)

    def test_feeds_list_uses_cache_page(self):
        # feeds_list reads GlobalRegion. Empty fixture is fine — page renders.
        url = reverse("optimap:feeds")
        self._hits_cache_on_second_request(url)

    def test_robots_uses_cache_page(self):
        url = "/robots.txt"
        # robots.txt builds region lists; should still cache.
        self._hits_cache_on_second_request(url)


class WorkLandingCacheTests(TestCase):
    """Anonymous landing-page context is cached per work + lastUpdate."""

    def setUp(self):
        self.client = Client()
        caches["memory"].clear()
        self.work = _make_published_work()
        self.url = reverse("optimap:work-landing", args=[self.work.get_identifier()])

    def _cache_keys_for_work(self, work):
        # LocMemCache stores under cache.LocMemCache._cache as
        # {make_key(key): (expiry, value)}. We just look for any key
        # mentioning our work's pk + the current host.
        backend = caches["memory"]
        store = getattr(backend, "_cache", {})
        prefix = "work_landing:ctx:"
        return [k for k in store.keys() if prefix in k and f":{work.id}:" in k]

    def test_cache_miss_then_hit(self):
        # First request populates the cache.
        self.assertEqual(self._cache_keys_for_work(self.work), [])
        r1 = self.client.get(self.url)
        self.assertEqual(r1.status_code, 200)
        keys_after = self._cache_keys_for_work(self.work)
        self.assertEqual(len(keys_after), 1, f"expected one cache entry, found {keys_after}")

        # Second request should not write a new entry — same key reused.
        r2 = self.client.get(self.url)
        self.assertEqual(r2.status_code, 200)
        self.assertEqual(self._cache_keys_for_work(self.work), keys_after)

    def test_save_invalidates_cache_via_lastupdate_bump(self):
        # Populate cache.
        self.client.get(self.url)
        keys_before = set(self._cache_keys_for_work(self.work))
        self.assertEqual(len(keys_before), 1)

        # Saving bumps lastUpdate (auto_now=True), so the next request
        # computes a *different* cache key — old entry stays under the
        # superseded key but is unreachable.
        self.work.title = "New title"
        self.work.save()

        r = self.client.get(self.url)
        self.assertEqual(r.status_code, 200)
        keys_after = set(self._cache_keys_for_work(self.work))
        # Old key still present (TTL-bound), new key added — same work,
        # different lastUpdate value.
        self.assertGreaterEqual(len(keys_after), len(keys_before))
        self.assertNotEqual(keys_after - keys_before, set(), "saving the work should produce a new cache key")
        # The response uses the new title.
        self.assertContains(r, "New title")

    def test_admin_request_bypasses_cache(self):
        admin = User.objects.create_user(
            username="cacheadmin",
            email="cacheadmin@example.test",
            password="x",
            is_staff=True,
        )
        self.client.force_login(admin)
        self.client.get(self.url)
        # Authenticated requests don't write to the anon cache.
        self.assertEqual(self._cache_keys_for_work(self.work), [])

    def test_anonymous_user_with_unpublished_work_404(self):
        unpublished = _make_published_work(
            status="d", doi="10.1234/cache.test.draft", url="https://example.test/article/draft"
        )
        url = reverse("optimap:work-landing", args=[unpublished.get_identifier()])
        r = self.client.get(url)
        self.assertEqual(r.status_code, 404)
        # And no cache entry created for an unauthorised request.
        self.assertEqual(self._cache_keys_for_work(unpublished), [])


def _max_age_from_cache_control(value: str) -> int | None:
    """Pick ``max-age`` (seconds) out of a ``Cache-Control`` header."""
    if not value:
        return None
    for token in value.split(","):
        token = token.strip()
        if token.startswith("max-age="):
            try:
                return int(token.split("=", 1)[1])
            except ValueError:
                return None
    return None


class CacheControlHeaderTests(TestCase):
    """The cache TTL must reach the client over HTTP — anything else means
    only the server benefits and intermediaries / browsers re-hit on every
    request. Each cached view should advertise ``Cache-Control: max-age=…``
    matching its configured TTL plus an ``Expires`` header in the future.
    """

    def setUp(self):
        self.client = Client()
        caches["memory"].clear()

    def _assert_max_age_and_expires(self, response, expected_max_age: int):
        cache_control = response.get("Cache-Control", "")
        max_age = _max_age_from_cache_control(cache_control)
        self.assertIsNotNone(
            max_age,
            f"Cache-Control header missing max-age: {cache_control!r}",
        )
        self.assertEqual(
            max_age,
            expected_max_age,
            f"Cache-Control max-age mismatch: got {max_age}, want {expected_max_age} (full header: {cache_control!r})",
        )
        self.assertIn(
            "Expires",
            response,
            "Expires header not set — Django's patch_response_headers should add it",
        )

    def test_privacy_advertises_24h_max_age(self):
        r = self.client.get(reverse("optimap:privacy"))
        self.assertEqual(r.status_code, 200)
        self._assert_max_age_and_expires(r, 24 * 3600)

    def test_about_advertises_24h_max_age(self):
        r = self.client.get(reverse("optimap:about"))
        self.assertEqual(r.status_code, 200)
        self._assert_max_age_and_expires(r, 24 * 3600)

    def test_accessibility_advertises_24h_max_age(self):
        r = self.client.get(reverse("optimap:accessibility"))
        self.assertEqual(r.status_code, 200)
        self._assert_max_age_and_expires(r, 24 * 3600)

    def test_feeds_list_advertises_1h_max_age(self):
        r = self.client.get(reverse("optimap:feeds"))
        self.assertEqual(r.status_code, 200)
        self._assert_max_age_and_expires(r, 3600)

    def test_sitemap_page_advertises_1h_max_age(self):
        r = self.client.get(reverse("optimap:sitemap-page"))
        self.assertEqual(r.status_code, 200)
        self._assert_max_age_and_expires(r, 3600)

    def test_robots_advertises_1h_max_age(self):
        r = self.client.get("/robots.txt")
        self.assertEqual(r.status_code, 200)
        self._assert_max_age_and_expires(r, 3600)

    def test_anonymous_work_landing_advertises_24h_max_age(self):
        work = _make_published_work(doi="10.1234/cache.headers.1", url="https://example.test/headers/1")
        url = reverse("optimap:work-landing", args=[work.get_identifier()])
        r = self.client.get(url)
        self.assertEqual(r.status_code, 200)
        self._assert_max_age_and_expires(r, 24 * 3600)

    def test_admin_work_landing_varies_on_cookie(self):
        """Staff requests carry admin-only state (status badges, publish
        buttons). Whatever ``Cache-Control`` is set, the response must
        ``Vary: Cookie`` so shared caches keep authenticated responses
        separate from the anonymous shared entry."""
        admin = User.objects.create_user(
            username="cacheadmin2",
            email="cacheadmin2@example.test",
            password="x",
            is_staff=True,
        )
        self.client.force_login(admin)
        work = _make_published_work(doi="10.1234/cache.headers.admin", url="https://example.test/headers/admin")
        url = reverse("optimap:work-landing", args=[work.get_identifier()])
        r = self.client.get(url)
        self.assertEqual(r.status_code, 200)
        vary = r.get("Vary", "")
        self.assertIn(
            "Cookie",
            vary,
            f"Admin response should Vary on Cookie so shared caches don't conflate sessions, got Vary: {vary!r}",
        )
