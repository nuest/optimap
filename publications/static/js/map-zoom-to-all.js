// publications/static/js/map-zoom-to-all.js

/**
 * MapZoomToAllControl
 *
 * Adds a custom Leaflet control button that zooms the map to show all features.
 * This provides users with an easy way to reset the map view to display all publications.
 *
 * Usage:
 *   const zoomControl = new MapZoomToAllControl(map, featureGroup);
 *
 * @param {L.Map} map - The Leaflet map instance
 * @param {L.FeatureGroup} featureGroup - The feature group containing all features to zoom to
 */
class MapZoomToAllControl {
  constructor(map, featureGroup) {
    this.map = map;
    this.featureGroup = featureGroup;
    this.control = null;

    this.init();
  }

  /**
   * Initialize the control and add it to the map
   */
  init() {
    const ZoomToAllControl = L.Control.extend({
      options: {
        position: 'topleft'
      },

      onAdd: (map) => {
        // Create the control container
        const container = L.DomUtil.create('div', 'leaflet-bar leaflet-control leaflet-control-zoom-to-all');

        // Create the button
        const button = L.DomUtil.create('a', 'leaflet-control-zoom-to-all-button', container);
        button.href = '#';
        button.title = 'Zoom to all features';
        button.setAttribute('role', 'button');
        button.setAttribute('aria-label', 'Zoom to all features');

        // Add icon using FontAwesome icon or Unicode fallback
        button.innerHTML = '<i class="fas fa-expand" aria-hidden="true"></i>';

        // Prevent map interactions when clicking the button
        L.DomEvent.disableClickPropagation(container);
        L.DomEvent.disableScrollPropagation(container);

        // Add click event handler
        L.DomEvent.on(button, 'click', (e) => {
          L.DomEvent.preventDefault(e);
          this.zoomToAllFeatures();
        });

        return container;
      }
    });

    // Add the control to the map
    this.control = new ZoomToAllControl();
    this.control.addTo(this.map);

    console.log('Zoom to all features control added');
  }

  /**
   * Zoom the map to fit all features in the feature group
   */
  zoomToAllFeatures() {
    const bounds = this.featureGroup.getBounds();

    if (bounds.isValid()) {
      // Fit the map to the bounds with some padding
      this.map.fitBounds(bounds, {
        padding: [50, 50],
        maxZoom: 18
      });

      console.log('Zoomed to all features');

      // Announce to screen readers
      this.announceToScreenReader('Map zoomed to show all features');
    } else {
      console.warn('No valid bounds to zoom to');
      this.announceToScreenReader('No features to display');
    }
  }

  /**
   * Announce messages to screen readers
   * @param {string} message - The message to announce
   */
  announceToScreenReader(message) {
    // Use existing status element if available, or create a temporary one
    let statusElement = document.getElementById('search-results-status');

    if (!statusElement) {
      statusElement = document.createElement('div');
      statusElement.setAttribute('role', 'status');
      statusElement.setAttribute('aria-live', 'polite');
      statusElement.className = 'sr-only';
      document.body.appendChild(statusElement);
    }

    statusElement.textContent = message;
  }

  /**
   * Remove the control from the map
   */
  destroy() {
    if (this.control) {
      this.map.removeControl(this.control);
      this.control = null;
      console.log('Zoom to all features control removed');
    }
  }
}

// Make the class globally available
window.MapZoomToAllControl = MapZoomToAllControl;
