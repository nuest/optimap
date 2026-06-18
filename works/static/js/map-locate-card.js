// SPDX-FileCopyrightText: 2025 OPTIMETA and KOMET projects <https://projects.tib.eu/komet>
// SPDX-License-Identifier: GPL-3.0-or-later

// works/static/js/map-locate-card.js

/**
 * MapLocateCardManager
 *
 * Wires the "Show on map" buttons rendered on work cards (class
 * `.show-on-map-btn`, carrying `data-work-id`) to the Leaflet map shown above
 * the card list (collection page, regional feed page).
 *
 * Clicking a button zooms/pans the map to that work's geometry, scrolls the
 * map into view, and reuses MapInteractionManager.selectPublication() to open
 * the popup and highlight the geometry — the same visual feedback a map click
 * produces.
 *
 * Click handling is delegated on `document`, so it keeps working after the map
 * layers are rebuilt (e.g. the page/all scope toggle replaces the layer group).
 *
 * Usage:
 *   new MapLocateCardManager(
 *     map,
 *     () => currentStatusLayers.getCombinedLayer(),  // current combined L.GeoJSON
 *     () => window.__optimapInteraction              // current MapInteractionManager
 *   );
 *
 * @param {L.Map} map - The Leaflet map instance.
 * @param {function(): L.GeoJSON} getCombinedLayer - Returns the current combined layer.
 * @param {function(): MapInteractionManager} getInteractionManager - Returns the current interaction manager (may be undefined).
 */
class MapLocateCardManager {
  constructor(map, getCombinedLayer, getInteractionManager) {
    this.map = map;
    this.getCombinedLayer = getCombinedLayer;
    this.getInteractionManager = getInteractionManager;

    document.addEventListener('click', (event) => {
      const btn = event.target.closest('.show-on-map-btn');
      if (!btn) {
        return;
      }
      event.preventDefault();
      this.locate(parseInt(btn.getAttribute('data-work-id'), 10));
    });
  }

  /** Find every layer belonging to the given work id in the current combined layer. */
  findLayers(workId) {
    const matches = [];
    const layer = this.getCombinedLayer && this.getCombinedLayer();
    if (!layer) {
      return matches;
    }
    layer.eachLayer((sub) => {
      if (!sub.feature) {
        return;
      }
      const fid = sub.feature.id || (sub.feature.properties && sub.feature.properties.id);
      if (fid === workId) {
        matches.push(sub);
      }
    });
    return matches;
  }

  /** Zoom to a work's geometry and open its popup / highlight it. */
  locate(workId) {
    if (!workId && workId !== 0) {
      return;
    }
    const matches = this.findLayers(workId);
    if (matches.length === 0) {
      if (typeof OPTIMAP_FLASH === 'function') {
        OPTIMAP_FLASH('info', 'This work has no location on the map.');
      }
      return;
    }

    const bounds = L.featureGroup(matches).getBounds();
    if (bounds.isValid()) {
      this.map.flyToBounds(bounds, { padding: [40, 40], maxZoom: 12 });
    }

    // Bring the map into view — it sits above a potentially long card list.
    const container = this.map.getContainer();
    if (container && typeof container.scrollIntoView === 'function') {
      container.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }

    // Reuse the existing selection logic for highlight + popup. Its
    // `overlappingFeatures` is empty here, so it opens the single popup.
    const interaction = this.getInteractionManager && this.getInteractionManager();
    if (interaction && typeof interaction.selectPublication === 'function') {
      interaction.selectPublication({ publicationId: workId, layer: matches[0] });
    } else if (matches[0].getPopup && matches[0].getPopup()) {
      matches[0].openPopup();
    }
  }
}
