// SPDX-FileCopyrightText: 2026 OPTIMETA and KOMET projects <https://projects.tib.eu/komet>
// SPDX-License-Identifier: GPL-3.0-or-later

// map-status-layers.js
// Splits a publication GeoJSON FeatureCollection into "Published" and "Unpublished"
// Leaflet layers, each registered as an independent overlay in the layer control.
// Used on the main map (admins see unpublished works) and on collection pages
// (curators see unpublished works). Anonymous / non-curator users only get
// `status='p'` features from the API/view, so the "Unpublished" overlay never
// appears for them.

(function (root) {
  function isUnpublished(feature) {
    const s = feature && feature.properties && feature.properties.status;
    return !!s && s !== 'p';
  }

  function unpublishedStyle(baseStyle) {
    return Object.assign({}, baseStyle, {
      opacity: 0.5,
      fillOpacity: 0.1,
      dashArray: '4, 4',
    });
  }

  class MapStatusLayersManager {
    /**
     * @param {L.Map} map - Leaflet map.
     * @param {L.Control.Layers} layerControl - Layer control to register overlays into.
     * @param {Array|Object} features - Array of GeoJSON Features or a FeatureCollection.
     * @param {Object} [options]
     * @param {Function} [options.styleFn] - Base style function (defaults to window.publicationStyle).
     * @param {Function} [options.popupFn] - Base onEachFeature function (defaults to window.publicationPopup).
     * @param {string}   [options.publishedLabel]   - Defaults to 'Published works'.
     * @param {string}   [options.unpublishedLabel] - Defaults to 'Unpublished works'.
     */
    constructor(map, layerControl, features, options) {
      options = options || {};
      this.map = map;
      this.layerControl = layerControl;

      const styleFn = options.styleFn || (typeof publicationStyle === 'function' ? publicationStyle : null);
      const popupFn = options.popupFn || (typeof publicationPopup === 'function' ? publicationPopup : null);
      const publishedLabel = options.publishedLabel || options.publishedLabelTemplate || 'Published works';
      const unpublishedLabel = options.unpublishedLabel || options.unpublishedLabelTemplate || 'Unpublished works';

      this.publishedGroup = L.featureGroup();
      this.unpublishedGroup = L.featureGroup();

      // L.geoJSON used as a single layer reference for managers that iterate
      // (interaction, keyboard, search). Not added to the map directly — its
      // children are routed to the two FeatureGroups, which ARE on the map.
      this.allLayer = L.geoJSON(features, {
        pointToLayer: (feature, latlng) => {
          const base = styleFn ? styleFn(feature) : {};
          const style = isUnpublished(feature) ? unpublishedStyle(base) : base;
          return publicationPointToLayer(feature, latlng, () => style);
        },
        style: (feature) => {
          const base = styleFn ? styleFn(feature) : {};
          return isUnpublished(feature) ? unpublishedStyle(base) : base;
        },
        onEachFeature: (feature, layer) => {
          if (popupFn) popupFn(feature, layer);
          if (isUnpublished(feature)) {
            this.unpublishedGroup.addLayer(layer);
          } else {
            this.publishedGroup.addLayer(layer);
          }
        },
      });

      // Parent group both managers (search/zoom) can still treat as the
      // single "publications group". Toggling it via map.addLayer/removeLayer
      // cascades to both children.
      this.publicationsGroup = L.featureGroup([this.publishedGroup, this.unpublishedGroup]);
      this.publicationsGroup.addTo(this.map);

      this._unpublishedLabel = unpublishedLabel;
      this._unpublishedRegistered = false;

      this.layerControl.addOverlay(this.publishedGroup, publishedLabel);
      if (this.unpublishedGroup.getLayers().length > 0) {
        this.layerControl.addOverlay(this.unpublishedGroup, unpublishedLabel);
        this._unpublishedRegistered = true;
      }
    }

    /**
     * Bounds spanning every feature regardless of group visibility.
     * Used for fitBounds() and zoom-to-all.
     */
    getBounds() {
      return this.publicationsGroup.getBounds();
    }

    /** @returns {L.GeoJSON} Combined layer (all features) for managers that iterate. */
    getCombinedLayer() {
      return this.allLayer;
    }

    /**
     * Single FeatureGroup handle suitable for MapSearchManager / MapZoomToAllControl
     * etc., which expect to call `.addTo(map)`, `map.removeLayer(group)`, and
     * `getBounds()` on a single object.
     */
    getPublicationsGroup() {
      return this.publicationsGroup;
    }

    /**
     * Add a new batch of GeoJSON features to the existing layers.
     * Called by the chunked-loading loop in main.js for each page after the first.
     * Routing to published/unpublished groups happens inside onEachFeature.
     * @param {Array} features - Array of GeoJSON feature objects.
     */
    addFeatures(features) {
      const hadUnpublished = this._unpublishedRegistered;
      this.allLayer.addData({ type: 'FeatureCollection', features });
      // Register the Unpublished overlay the first time an unpublished work appears.
      if (!hadUnpublished && this.unpublishedGroup.getLayers().length > 0) {
        this.layerControl.addOverlay(this.unpublishedGroup, this._unpublishedLabel);
        this._unpublishedRegistered = true;
      }
    }
  }

  root.MapStatusLayersManager = MapStatusLayersManager;
})(typeof window !== 'undefined' ? window : this);
