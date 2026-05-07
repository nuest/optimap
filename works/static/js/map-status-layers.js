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
  // Bootstrap badge classes per Work.STATUS_CHOICES (works/models.py).
  // Mirrors the badges added to collection_page.html in commit 64491b6.
  const STATUS_BADGE_CLASS = {
    p: 'badge-success',   // Published
    d: 'badge-secondary', // Draft
    h: 'badge-info',      // Harvested
    c: 'badge-primary',   // Contributed
    t: 'badge-warning',   // Testing
    w: 'badge-danger',    // Withdrawn
  };

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

  function statusBadgeHTML(feature) {
    const props = feature.properties || {};
    const status = props.status;
    if (!status || status === 'p') return '';
    const label = props.status_display || status;
    const cls = STATUS_BADGE_CLASS[status] || 'badge-secondary';
    return (
      '<div class="mb-2">' +
        '<span class="badge ' + cls + '" ' +
              'title="Publication status — visible to admins/curators only.">' +
          label +
        '</span> ' +
        '<small class="text-muted">— not visible to anonymous users</small>' +
      '</div>'
    );
  }

  class MapStatusLayersManager {
    /**
     * @param {L.Map} map - Leaflet map.
     * @param {L.Control.Layers} layerControl - Layer control to register overlays into.
     * @param {Array|Object} features - Array of GeoJSON Features or a FeatureCollection.
     * @param {Object} [options]
     * @param {Function} [options.styleFn] - Base style function (defaults to window.publicationStyle).
     * @param {Function} [options.popupFn] - Base onEachFeature function (defaults to window.publicationPopup).
     * @param {string}   [options.publishedLabelTemplate]   - Defaults to 'Published works ({n})'.
     * @param {string}   [options.unpublishedLabelTemplate] - Defaults to 'Unpublished works ({n})'.
     */
    constructor(map, layerControl, features, options) {
      options = options || {};
      this.map = map;
      this.layerControl = layerControl;

      const styleFn = options.styleFn || (typeof publicationStyle === 'function' ? publicationStyle : null);
      const popupFn = options.popupFn || (typeof publicationPopup === 'function' ? publicationPopup : null);
      const publishedLabelTemplate = options.publishedLabelTemplate || 'Published works ({n})';
      const unpublishedLabelTemplate = options.unpublishedLabelTemplate || 'Unpublished works ({n})';

      this.publishedGroup = L.featureGroup();
      this.unpublishedGroup = L.featureGroup();

      // L.geoJSON used as a single layer reference for managers that iterate
      // (interaction, keyboard, search). Not added to the map directly — its
      // children are routed to the two FeatureGroups, which ARE on the map.
      this.allLayer = L.geoJSON(features, {
        style: function (feature) {
          const base = styleFn ? styleFn(feature) : {};
          return isUnpublished(feature) ? unpublishedStyle(base) : base;
        },
        onEachFeature: function (feature, layer) {
          if (popupFn) popupFn(feature, layer);
          if (isUnpublished(feature)) {
            // Prepend a status badge to the popup content so curators/admins
            // can see at a glance that the work isn't public.
            const popup = layer.getPopup();
            if (popup) {
              const original = popup.getContent() || '';
              const badge = statusBadgeHTML(feature);
              let next;
              if (typeof original === 'string' && original.indexOf('<div>') === 0) {
                next = '<div>' + badge + original.slice('<div>'.length);
              } else {
                next = badge + original;
              }
              popup.setContent(next);
            }
          }
        },
      });

      let publishedCount = 0;
      let unpublishedCount = 0;
      this.allLayer.eachLayer((layer) => {
        if (layer.feature && isUnpublished(layer.feature)) {
          this.unpublishedGroup.addLayer(layer);
          unpublishedCount++;
        } else {
          this.publishedGroup.addLayer(layer);
          publishedCount++;
        }
      });
      this.publishedCount = publishedCount;
      this.unpublishedCount = unpublishedCount;

      // Parent group both managers (search/zoom) can still treat as the
      // single "publications group". Toggling it via map.addLayer/removeLayer
      // cascades to both children.
      this.publicationsGroup = L.featureGroup([this.publishedGroup, this.unpublishedGroup]);
      this.publicationsGroup.addTo(this.map);

      this.layerControl.addOverlay(
        this.publishedGroup,
        publishedLabelTemplate.replace('{n}', publishedCount)
      );
      if (unpublishedCount > 0) {
        this.layerControl.addOverlay(
          this.unpublishedGroup,
          unpublishedLabelTemplate.replace('{n}', unpublishedCount)
        );
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
  }

  root.MapStatusLayersManager = MapStatusLayersManager;
})(typeof window !== 'undefined' ? window : this);
