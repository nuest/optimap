// SPDX-FileCopyrightText: 2022 OPTIMETA and KOMET projects <https://projects.tib.eu/komet>
// SPDX-License-Identifier: GPL-3.0-or-later

// Shared Leaflet map factory.  Centralises the tile URL, attribution, and the
// options that prevent the map from showing multiple copies of the Earth when
// zoomed out (noWrap + maxBounds).

const OPTIMAP_OSM_URL  = 'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png';
const OPTIMAP_OSM_ATTR = 'Map data: © <a href="https://openstreetmap.org">OpenStreetMap</a> contributors';
const WORLD_BOUNDS     = [[-90, -180], [90, 180]];

/**
 * Create a Leaflet map with an OSM base layer and world-boundary constraints.
 *
 * @param {string|HTMLElement} elementId - Map container (id string or DOM element).
 * @param {object} mapOptions  - Extra L.map options merged over defaults.
 * @param {object} tileOptions - Extra L.tileLayer options merged over defaults.
 * @returns {{ map: L.Map, tileLayer: L.TileLayer }}
 */
function createBaseMap(elementId, mapOptions = {}, tileOptions = {}) {
  const map = L.map(elementId, {
    maxBounds: WORLD_BOUNDS,
    maxBoundsViscosity: 1.0,
    ...mapOptions,
  });
  const tileLayer = L.tileLayer(OPTIMAP_OSM_URL, {
    maxZoom: 18,
    noWrap: true,
    attribution: OPTIMAP_OSM_ATTR,
    ...tileOptions,
  }).addTo(map);
  return { map, tileLayer };
}
