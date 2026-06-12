// SPDX-FileCopyrightText: 2025 OPTIMETA and KOMET projects <https://projects.tib.eu/komet>
// SPDX-License-Identifier: GPL-3.0-or-later

// Shared Leaflet geometry style definitions used on all OPTIMAP maps.

const OPTIMAP_MAP_STYLES = {
  default: {
    color: '#158F9B',
    weight: 2,
    fillOpacity: 0.3,
  },
  highlight: {
    color: '#FF4500',
    weight: 5,
    fillOpacity: 0.6,
    fillColor: '#FF6B35',
  },
  selected: {
    color: '#FFD700',
    weight: 6,
    fillOpacity: 0.7,
    fillColor: '#FFA500',
    dashArray: '10, 5',
  },
};

function publicationStyle(/* feature */) {
  return OPTIMAP_MAP_STYLES.default;
}

/**
 * Shared pointToLayer for L.geoJSON — renders GeoJSON Point features as
 * circleMarkers so they match the styled polygon/line symbology instead of
 * falling back to Leaflet's default blue-pin marker.
 * @param {Object} feature - GeoJSON feature
 * @param {L.LatLng} latlng
 * @param {Function} [styleFn] - Optional override; defaults to publicationStyle.
 * @returns {L.CircleMarker}
 */
function publicationPointToLayer(feature, latlng, styleFn) {
  const style = (styleFn || publicationStyle)(feature);
  return L.circleMarker(latlng, Object.assign({ radius: 6 }, style));
}
