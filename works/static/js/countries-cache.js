// SPDX-FileCopyrightText: 2026 OPTIMETA and KOMET projects <https://projects.tib.eu/komet>
// SPDX-License-Identifier: GPL-3.0-or-later

// countries-cache.js
// Shared loader + browser cache for the all-countries GeoJSON (#29). Fetches the
// simplified Natural Earth outlines from /api/v1/countries/ once and stores them
// in localStorage so the main map's MapCountriesManager and the country landing
// pages (/at/<country>/) reuse the same data across visits without re-fetching.

(function (window) {
  const STORAGE_KEY = 'optimap.countries.v1';
  const TTL_MS = 7 * 24 * 60 * 60 * 1000; // refresh at most once a week
  const API_URL = '/api/v1/countries/';

  let inflight = null; // de-dupe concurrent callers within a single page load

  // Reduce the various shapes the API/paginator can return to a features array.
  function normalize(data) {
    if (data && data.results && data.results.type === 'FeatureCollection') return data.results.features;
    if (data && data.results && Array.isArray(data.results)) return data.results;
    if (data && data.features && Array.isArray(data.features)) return data.features;
    if (Array.isArray(data)) return data;
    return null;
  }

  function readCache() {
    try {
      const raw = window.localStorage.getItem(STORAGE_KEY);
      if (!raw) return null;
      const parsed = JSON.parse(raw);
      if (!parsed || !Array.isArray(parsed.features) || !parsed.fetchedAt) return null;
      if (Date.now() - parsed.fetchedAt > TTL_MS) return null;
      return parsed.features;
    } catch (e) {
      return null;
    }
  }

  function writeCache(features) {
    try {
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify({ fetchedAt: Date.now(), features: features }));
    } catch (e) {
      // localStorage full or unavailable (private mode/quota) — the caller still
      // has the data in memory for this page, so this is non-fatal.
    }
  }

  // Resolve to an array of GeoJSON country features, from cache when fresh.
  function loadCountryFeatures() {
    const cached = readCache();
    if (cached) return Promise.resolve(cached);
    if (inflight) return inflight;
    inflight = fetch(API_URL)
      .then((r) => r.json())
      .then((data) => {
        const features = normalize(data);
        if (!features) {
          console.error('Unexpected /api/v1/countries/ response format:', data);
          return [];
        }
        writeCache(features);
        return features;
      })
      .catch((err) => {
        console.error('Failed to load countries:', err);
        return [];
      })
      .finally(() => {
        inflight = null;
      });
    return inflight;
  }

  // Find a single country feature by ISO 3166-1 alpha-2 code (case-insensitive).
  function findByIso(features, iso) {
    if (!iso || !Array.isArray(features)) return null;
    const wanted = String(iso).toUpperCase();
    return (
      features.find(
        (f) => f && f.properties && String(f.properties.iso_code).toUpperCase() === wanted
      ) || null
    );
  }

  window.OptimapCountries = { loadCountryFeatures: loadCountryFeatures, findByIso: findByIso };
})(window);
