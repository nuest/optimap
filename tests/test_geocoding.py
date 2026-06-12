# SPDX-FileCopyrightText: 2026 OPTIMETA and KOMET projects <https://projects.tib.eu/komet>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Reverse-geocoding service + signal tests (issue #222).

The geopy/Nominatim layer is patched throughout — these tests must never
hit the network. We exercise:

- Single-point caching (cache miss → geocoder call, cache hit → no call)
  and ~100 m quantisation (close-by coordinates share an entry).
- Graceful degradation on errors (no exceptions, returns ``(None, None)``).
- ``geocode_geometry`` walks every representative point of multi-point
  geometries and returns the lowest common ancestor in the address
  hierarchy — works clustered in one country share that country's code,
  works spanning multiple countries return ``(None, None)`` for placename
  *and* country, and the LCA collapses to the deepest level all points
  agree on (city → state → country → nothing).
- The ``pre_save`` signal calls ``geocode_geometry`` (not the centroid
  shortcut), is gated by ``OPTIMAP_GEOCODE_WORKS_ON_SAVE``, and preserves
  existing fields when *all* per-point geocodes fail (transient outage)
  but clears them when the LCA is genuinely empty.
"""

from __future__ import annotations

import json
from unittest import mock

from django.contrib.gis.geos import GeometryCollection, GEOSGeometry, Point
from django.core.cache import caches
from django.test import TestCase, override_settings

from works.models import Source, Work
from works.services import geocoding


def _polygon_collection(coords):
    geom = GEOSGeometry(json.dumps({"type": "Polygon", "coordinates": [coords]}), srid=4326)
    return GeometryCollection(geom, srid=4326)


def _make_source():
    return Source.objects.create(
        name="Geocoder Test Journal",
        url_field="https://example.test/oai",
        homepage_url="https://example.test/",
        harvest_interval_minutes=1440,
    )


class _FakeLocation:
    """Stand-in for ``geopy.location.Location`` with full ``addressdetails``."""

    def __init__(self, display_name: str, address: dict | None = None):
        self.address = display_name
        self.raw = {
            "display_name": display_name,
            "address": dict(address or {}),
        }


# Pre-canned address dicts for a handful of cities — keep tests legible
# without inlining sprawling Nominatim payloads.
_BERLIN = {
    "country_code": "de",
    "country": "Germany",
    "state": "Berlin",
    "city": "Berlin",
}
_HAMBURG = {
    "country_code": "de",
    "country": "Germany",
    "state": "Hamburg",
    "city": "Hamburg",
}
_MUNICH = {
    "country_code": "de",
    "country": "Germany",
    "state": "Bavaria",
    "city": "Munich",
}
_PARIS = {
    "country_code": "fr",
    "country": "France",
    "state": "Île-de-France",
    "city": "Paris",
}


class ReverseGeocodeServiceTests(TestCase):
    def setUp(self):
        # Wipe the in-memory cache between tests so cached results from one
        # test don't satisfy another test's cache-miss assertion.
        caches[geocoding._CACHE_ALIAS].clear()

    def test_cache_miss_invokes_geocoder_and_caches_result(self):
        fake_geocoder = mock.Mock()
        fake_geocoder.reverse.return_value = _FakeLocation(
            "Berlin, Germany",
            _BERLIN,
        )
        with mock.patch.object(geocoding, "_build_geocoder", return_value=fake_geocoder):
            placename, country = geocoding.reverse_geocode(52.52, 13.4)
        self.assertEqual(placename, "Berlin, Germany")
        self.assertEqual(country, "DE")  # upper-cased in the helper.
        # Second call hits the cache — geocoder must not be re-invoked.
        with mock.patch.object(geocoding, "_build_geocoder") as build_mock:
            placename2, country2 = geocoding.reverse_geocode(52.52, 13.4)
            build_mock.assert_not_called()
        self.assertEqual((placename2, country2), (placename, country))

    def test_quantised_cache_key_buckets_close_by_coordinates(self):
        # Same key at 3 decimal places — a 0.0005° offset (~50 m) shouldn't
        # bust the cache.
        self.assertEqual(
            geocoding._cache_key(52.52000, 13.40000),
            geocoding._cache_key(52.52030, 13.39980),
        )

    def test_geocoder_failure_returns_none_pair_and_does_not_cache(self):
        fake_geocoder = mock.Mock()
        fake_geocoder.reverse.side_effect = RuntimeError("network down")
        with mock.patch.object(geocoding, "_build_geocoder", return_value=fake_geocoder):
            result = geocoding.reverse_geocode(0.0, 0.0)
        self.assertEqual(result, (None, None))
        # Transient failures must NOT poison the 30-day cache.
        self.assertIsNone(caches[geocoding._CACHE_ALIAS].get(geocoding._cache_key(0.0, 0.0)))

    def test_no_location_returns_none_pair(self):
        fake_geocoder = mock.Mock()
        fake_geocoder.reverse.return_value = None
        with mock.patch.object(geocoding, "_build_geocoder", return_value=fake_geocoder):
            result = geocoding.reverse_geocode(0.0, 0.0)
        self.assertEqual(result, (None, None))


class _LookupTable:
    """Side-effect for ``_reverse_geocode_lookup`` keyed on rounded ``(lat, lon)``.

    Mirrors the cache-key quantisation so tests can declare lookups by their
    actual coordinates.
    """

    def __init__(self, table: dict[tuple[float, float], dict | None]):
        self.table = {(round(k[0], 3), round(k[1], 3)): v for k, v in table.items()}

    def __call__(self, lat, lon):
        info = self.table.get((round(lat, 3), round(lon, 3)))
        return info  # may be None to simulate "Nominatim returned no result"


class GeocodeGeometryLcaTests(TestCase):
    """Lowest-common-ancestor logic for multi-point geometries."""

    def setUp(self):
        caches[geocoding._CACHE_ALIAS].clear()

    @staticmethod
    def _gc(*lonlats):
        return GeometryCollection(
            *(Point(lon, lat, srid=4326) for lon, lat in lonlats),
            srid=4326,
        )

    def test_single_point_returns_full_display_name(self):
        # Equivalence with reverse_geocode: one point → that placename.
        lookup = _LookupTable(
            {
                (52.52, 13.40): {"address": _BERLIN, "display_name": "Berlin, Germany"},
            }
        )
        with mock.patch.object(
            geocoding,
            "_reverse_geocode_lookup",
            side_effect=lookup,
        ):
            placename, country, n = geocoding.geocode_geometry(self._gc((13.40, 52.52)))
        # Most specific first: city, state, country.
        self.assertEqual(placename, "Berlin, Berlin, Germany")
        self.assertEqual(country, "DE")
        self.assertEqual(n, 1)

    def test_two_points_same_city_share_full_lca(self):
        lookup = _LookupTable(
            {
                (52.520, 13.400): {"address": _BERLIN, "display_name": "Berlin"},
                (52.515, 13.380): {"address": _BERLIN, "display_name": "Berlin"},
            }
        )
        with mock.patch.object(
            geocoding,
            "_reverse_geocode_lookup",
            side_effect=lookup,
        ):
            placename, country, n = geocoding.geocode_geometry(self._gc((13.400, 52.520), (13.380, 52.515)))
        # Country, state, city all agree.
        self.assertEqual(placename, "Berlin, Berlin, Germany")
        self.assertEqual(country, "DE")
        self.assertEqual(n, 2)

    def test_two_points_different_states_collapse_to_country(self):
        # Berlin (state=Berlin) + Munich (state=Bavaria) → state diverges,
        # LCA stops at country.
        lookup = _LookupTable(
            {
                (52.52, 13.40): {"address": _BERLIN, "display_name": "Berlin"},
                (48.14, 11.58): {"address": _MUNICH, "display_name": "Munich"},
            }
        )
        with mock.patch.object(
            geocoding,
            "_reverse_geocode_lookup",
            side_effect=lookup,
        ):
            placename, country, n = geocoding.geocode_geometry(self._gc((13.40, 52.52), (11.58, 48.14)))
        self.assertEqual(placename, "Germany")
        self.assertEqual(country, "DE")
        self.assertEqual(n, 2)

    def test_points_in_different_countries_have_no_lca(self):
        lookup = _LookupTable(
            {
                (52.52, 13.40): {"address": _BERLIN, "display_name": "Berlin"},
                (48.86, 2.35): {"address": _PARIS, "display_name": "Paris"},
            }
        )
        with mock.patch.object(
            geocoding,
            "_reverse_geocode_lookup",
            side_effect=lookup,
        ):
            placename, country, n = geocoding.geocode_geometry(self._gc((13.40, 52.52), (2.35, 48.86)))
        self.assertIsNone(placename)
        self.assertIsNone(country)
        self.assertEqual(n, 2)

    def test_failed_lookups_skip_address_but_count_stays_at_successes(self):
        # One point geocodes successfully, the other returns None
        # (Nominatim has no result there). The LCA is just the successful
        # address, n == 1.
        lookup = _LookupTable(
            {
                (52.52, 13.40): {"address": _BERLIN, "display_name": "Berlin"},
                (0.0, 0.0): None,
            }
        )
        with mock.patch.object(
            geocoding,
            "_reverse_geocode_lookup",
            side_effect=lookup,
        ):
            placename, country, n = geocoding.geocode_geometry(self._gc((13.40, 52.52), (0.0, 0.0)))
        self.assertEqual(country, "DE")
        self.assertIn("Berlin", placename)
        self.assertEqual(n, 1)

    def test_polygon_samples_envelope_corners_plus_interior(self):
        # A polygon must sample the four corners of its bounding box plus an
        # interior point, so cross-border polygons aren't reduced to a single
        # interior placename. The 4-vertex closing ring is still NOT
        # geocoded vertex-by-vertex (would explode for high-resolution rings).
        from django.contrib.gis.geos import Polygon

        poly = Polygon(
            ((10.0, 50.0), (11.0, 50.0), (11.0, 51.0), (10.0, 51.0), (10.0, 50.0)),
            srid=4326,
        )
        gc = GeometryCollection(poly, srid=4326)
        seen_coords: list[tuple[float, float]] = []

        def lookup(lat, lon):
            seen_coords.append((round(lat, 3), round(lon, 3)))
            return {"address": _BERLIN, "display_name": "Berlin"}

        with mock.patch.object(
            geocoding,
            "_reverse_geocode_lookup",
            side_effect=lookup,
        ):
            placename, country, n = geocoding.geocode_geometry(gc)
        # Four corners + one interior point — five lookups, not the five
        # ring vertices (which would include the duplicated closing point).
        self.assertEqual(len(seen_coords), 5, f"polygon: corners + interior, got {seen_coords}")
        self.assertEqual(
            set(
                [
                    c
                    for c in seen_coords
                    if c
                    in {
                        (50.0, 10.0),
                        (50.0, 11.0),
                        (51.0, 10.0),
                        (51.0, 11.0),
                    }
                ]
            ),
            {(50.0, 10.0), (50.0, 11.0), (51.0, 10.0), (51.0, 11.0)},
            "all four envelope corners must be sampled",
        )
        self.assertEqual(country, "DE")

    def test_polygon_spanning_two_countries_lca_falls_back(self):
        # Bug demoed by work id=10 on the deployed instance: a polygon
        # straddling Germany and Poland was getting "Mniszki, …, Poland" as
        # placename because only the centroid was geocoded. With corners
        # sampled, two corners hit Germany, two hit Poland → LCA collapses
        # past country (no shared continent in our test fixture either) and
        # the work no longer claims a misleading specific placename.
        from django.contrib.gis.geos import Polygon

        # Envelope corners → (lat, lon):
        #   (50, 10) DE, (50, 20) PL, (52, 10) DE, (52, 20) PL
        # Interior (point_on_surface for an axis-aligned rectangle) → (51, 15) — DE.
        _POLAND = {
            "country_code": "pl",
            "country": "Poland",
            "state": "Łódź Voivodeship",
            "city": "Mniszki",
        }
        lookup = _LookupTable(
            {
                (50.0, 10.0): {"address": _BERLIN, "display_name": "Berlin"},
                (50.0, 20.0): {"address": _POLAND, "display_name": "Mniszki"},
                (52.0, 10.0): {"address": _BERLIN, "display_name": "Berlin"},
                (52.0, 20.0): {"address": _POLAND, "display_name": "Mniszki"},
                (51.0, 15.0): {"address": _BERLIN, "display_name": "Berlin"},
            }
        )
        poly = Polygon(
            ((10.0, 50.0), (20.0, 50.0), (20.0, 52.0), (10.0, 52.0), (10.0, 50.0)),
            srid=4326,
        )
        gc = GeometryCollection(poly, srid=4326)
        with mock.patch.object(
            geocoding,
            "_reverse_geocode_lookup",
            side_effect=lookup,
        ):
            placename, country, n = geocoding.geocode_geometry(gc)
        # Two countries appear among the corners → no shared country → both
        # placename and country must be None, not the centroid's interior.
        self.assertIsNone(placename, f"expected None, got {placename!r}")
        self.assertIsNone(country)
        self.assertEqual(n, 5)

    def test_max_points_caps_geocoder_calls(self):
        # 30 points but max_points=5 → only 5 lookups.
        gc = GeometryCollection(
            *(Point(0.001 * i, 0.001 * i, srid=4326) for i in range(30)),
            srid=4326,
        )
        call_count = {"n": 0}

        def lookup(lat, lon):
            call_count["n"] += 1
            return {"address": _BERLIN, "display_name": "Berlin"}

        with mock.patch.object(
            geocoding,
            "_reverse_geocode_lookup",
            side_effect=lookup,
        ):
            geocoding.geocode_geometry(gc, max_points=5)
        self.assertEqual(call_count["n"], 5)


class WorkPreSaveGeocodeSignalTests(TestCase):
    def setUp(self):
        caches[geocoding._CACHE_ALIAS].clear()
        self.source = _make_source()
        self.geom = GeometryCollection(
            Point(13.4, 52.52, srid=4326),
            srid=4326,
        )

    @override_settings(GEOCODE_WORKS_ON_SAVE=False)
    def test_signal_inert_when_setting_false(self):
        # The setting gates the entire signal — geocode_geometry must not
        # be called when it's False.
        with mock.patch("works.services.geocoding.geocode_geometry") as gg:
            work = Work.objects.create(
                title="Signal-off work",
                source=self.source,
                geometry=self.geom,
                status="p",
                doi="10.1234/test.signal.off",
                url="https://example.test/article/signal-off",
            )
            gg.assert_not_called()
        self.assertIsNone(work.placename)
        self.assertIsNone(work.country_code)

    @override_settings(GEOCODE_WORKS_ON_SAVE=True)
    def test_signal_populates_placename_and_country_when_enabled(self):
        with mock.patch(
            "works.services.geocoding.geocode_geometry",
            return_value=("Berlin, Germany", "DE", 1),
        ):
            work = Work.objects.create(
                title="Signal-on work",
                source=self.source,
                geometry=self.geom,
                status="p",
                doi="10.1234/test.signal.on",
                url="https://example.test/article/signal-on",
            )
        self.assertEqual(work.placename, "Berlin, Germany")
        self.assertEqual(work.country_code, "DE")

    @override_settings(GEOCODE_WORKS_ON_SAVE=True)
    def test_signal_inert_when_no_geometry(self):
        with mock.patch("works.services.geocoding.geocode_geometry") as gg:
            work = Work.objects.create(
                title="No-geometry work",
                source=self.source,
                geometry=GeometryCollection(),
                status="p",
                doi="10.1234/test.signal.empty",
                url="https://example.test/article/signal-empty",
            )
            gg.assert_not_called()
        self.assertIsNone(work.placename)
        self.assertIsNone(work.country_code)

    @override_settings(GEOCODE_WORKS_ON_SAVE=True)
    def test_signal_preserves_fields_when_all_geocodes_fail(self):
        # n_geocoded=0 means every Nominatim call failed — don't blank a
        # previously-populated placename on a transient outage.
        with mock.patch(
            "works.services.geocoding.geocode_geometry",
            return_value=("Berlin, Germany", "DE", 1),
        ):
            work = Work.objects.create(
                title="Preserve work",
                source=self.source,
                geometry=self.geom,
                status="p",
                doi="10.1234/test.signal.preserve",
                url="https://example.test/article/signal-preserve",
            )
        with mock.patch(
            "works.services.geocoding.geocode_geometry",
            return_value=(None, None, 0),
        ):
            work.title = "Preserve work (edited)"
            work.save()
        work.refresh_from_db()
        self.assertEqual(work.placename, "Berlin, Germany")
        self.assertEqual(work.country_code, "DE")

    @override_settings(GEOCODE_WORKS_ON_SAVE=True)
    def test_signal_clears_fields_on_real_no_lca(self):
        # n_geocoded > 0 but LCA is None → genuine spans-multiple-countries
        # case. Honest behaviour: clear the now-incorrect placename.
        with mock.patch(
            "works.services.geocoding.geocode_geometry",
            return_value=("Berlin, Germany", "DE", 1),
        ):
            work = Work.objects.create(
                title="Clear work",
                source=self.source,
                geometry=self.geom,
                status="p",
                doi="10.1234/test.signal.clear",
                url="https://example.test/article/signal-clear",
            )
        with mock.patch(
            "works.services.geocoding.geocode_geometry",
            return_value=(None, None, 2),
        ):
            work.title = "Clear work (edited)"
            work.save()
        work.refresh_from_db()
        self.assertIsNone(work.placename)
        self.assertIsNone(work.country_code)
