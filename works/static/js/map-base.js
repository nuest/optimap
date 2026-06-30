// SPDX-FileCopyrightText: 2022 OPTIMETA and KOMET projects <https://projects.tib.eu/komet>
// SPDX-License-Identifier: GPL-3.0-or-later

// Shared Leaflet map factory.  Centralises the tile URL, attribution, and the
// options that prevent the map from showing multiple copies of the Earth when
// zoomed out (noWrap + maxBounds).

const OPTIMAP_OSM_URL  = 'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png';
const OPTIMAP_OSM_ATTR = 'Map data: © <a href="https://openstreetmap.org">OpenStreetMap</a> contributors';
const WORLD_BOUNDS     = [[-90, -180], [90, 180]];

// Parsed once on first call; the script tag content never changes after page load.
let _basemapDefsCache = null;

/**
 * Read enabled base-layer definitions from the server-injected json_script.
 * Returns [] when the script tag is absent or invalid (tests, non-DB contexts).
 */
function _readBasemapDefs() {
  if (_basemapDefsCache !== null) return _basemapDefsCache;
  const el = document.getElementById('optimap-basemaps');
  try { _basemapDefsCache = (el && JSON.parse(el.textContent)) || []; }
  catch (_) { _basemapDefsCache = []; }
  return _basemapDefsCache;
}

/**
 * Create a Leaflet map with a base layer switcher built from the admin-managed
 * ``BaseMapLayer`` table (injected via ``#optimap-basemaps`` json_script).
 *
 * Falls back to a plain OSM tile layer when no provider data is available
 * (e.g. during tests or before the first migration).
 *
 * @param {string|HTMLElement} elementId  - Map container id string or DOM element.
 * @param {object}             mapOptions - Extra L.map options merged over defaults.
 * @param {object}             tileOptions - Extra L.tileLayer options (fallback only).
 * @returns {{ map: L.Map, tileLayer: L.TileLayer, baseLayers: object, layerControl: L.Control.Layers }}
 */
function createBaseMap(elementId, mapOptions = {}, tileOptions = {}) {
  const map = L.map(elementId, {
    maxBounds: WORLD_BOUNDS,
    maxBoundsViscosity: 1.0,
    ...mapOptions,
  });

  const defs = _readBasemapDefs();
  let tileLayer = null;
  const baseLayers = {};

  if (defs.length > 0) {
    const hasProvider = typeof L.tileLayer.provider === 'function';
    for (const def of defs) {
      let layer;
      if (def.provider_key === 'BasemapWorldVector') {
        if (typeof L.maplibreGL !== 'function') {
          console.warn('MapLibre GL Leaflet plugin not loaded — skipping layer:', def.label);
          continue;
        }
        layer = L.maplibreGL({ style: def.options.style || '' });
      } else {
        if (!hasProvider) continue;
        // noWrap prevents tile repetition at the antimeridian; always applied,
        // but provider-specific options can override it when needed.
        layer = L.tileLayer.provider(def.provider_key, { noWrap: true, ...def.options });
      }
      baseLayers[def.label] = layer;
      if (def.default && !tileLayer) tileLayer = layer;
    }
    // Guarantee a default when none was flagged
    if (!tileLayer && Object.keys(baseLayers).length > 0) {
      tileLayer = Object.values(baseLayers)[0];
    }
  }

  if (!tileLayer) {
    // Fallback: plain OSM (no provider plugin or no DB data)
    tileLayer = L.tileLayer(OPTIMAP_OSM_URL, {
      maxZoom: 18,
      noWrap: true,
      attribution: OPTIMAP_OSM_ATTR,
      ...tileOptions,
    });
    baseLayers['OpenStreetMap'] = tileLayer;
  }

  tileLayer.addTo(map);
  const layerControl = L.control.layers(baseLayers, {}).addTo(map);

  return { map, tileLayer, baseLayers, layerControl };
}
