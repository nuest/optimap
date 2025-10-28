// publications/static/js/map-keyboard-navigation.js
// Keyboard navigation accessibility for interactive map

/**
 * Map Keyboard Navigation Manager
 * Provides keyboard accessibility for the Leaflet map
 * - Arrow keys: Pan map
 * - +/- keys: Zoom in/out
 * - Enter/Space: Activate focused feature
 * - Tab: Cycle through features
 * - Escape: Close popup
 */
class MapKeyboardNavigation {
  constructor(map, publicationsLayer, interactionManager) {
    this.map = map;
    this.publicationsLayer = publicationsLayer;
    this.interactionManager = interactionManager;
    this.focusedFeatureIndex = -1;
    this.features = [];
    this.isMapFocused = false;

    this.init();
  }

  init() {
    // Make map container focusable
    const mapContainer = this.map.getContainer();
    mapContainer.setAttribute('tabindex', '0');
    mapContainer.setAttribute('role', 'application');
    mapContainer.setAttribute('aria-label', 'Interactive map of publications. Use arrow keys to pan, plus and minus keys to zoom, tab to cycle through publications, enter to select.');

    // Collect all features
    this.collectFeatures();

    // Add keyboard event listeners
    this.setupKeyboardHandlers();

    // Add focus/blur handlers
    this.setupFocusHandlers();
  }

  /**
   * Collect all features from the publications layer
   */
  collectFeatures() {
    this.features = [];
    this.publicationsLayer.eachLayer((layer) => {
      if (layer.feature) {
        this.features.push({
          layer: layer,
          feature: layer.feature,
          publicationId: layer.feature.id || layer.feature.properties.id
        });
      }
    });
    console.log(`Keyboard navigation: ${this.features.length} features available`);
  }

  /**
   * Setup keyboard event handlers
   */
  setupKeyboardHandlers() {
    const mapContainer = this.map.getContainer();

    mapContainer.addEventListener('keydown', (e) => {
      if (!this.isMapFocused) return;

      const handled = this.handleKeyPress(e);
      if (handled) {
        e.preventDefault();
        e.stopPropagation();
      }
    });
  }

  /**
   * Setup focus handlers to track when map has focus
   */
  setupFocusHandlers() {
    const mapContainer = this.map.getContainer();

    mapContainer.addEventListener('focus', () => {
      this.isMapFocused = true;
      console.log('Map focused - keyboard navigation active');
      this.announce('Map focused. Use arrow keys to pan, plus and minus to zoom, tab to cycle through publications.');
    });

    mapContainer.addEventListener('blur', () => {
      this.isMapFocused = false;
      console.log('Map unfocused - keyboard navigation inactive');
    });
  }

  /**
   * Handle keyboard input
   */
  handleKeyPress(e) {
    const key = e.key;
    const panAmount = 100; // pixels

    switch(key) {
      // Arrow keys - pan map
      case 'ArrowUp':
        this.map.panBy([0, -panAmount]);
        this.announce('Panned up');
        return true;

      case 'ArrowDown':
        this.map.panBy([0, panAmount]);
        this.announce('Panned down');
        return true;

      case 'ArrowLeft':
        this.map.panBy([-panAmount, 0]);
        this.announce('Panned left');
        return true;

      case 'ArrowRight':
        this.map.panBy([panAmount, 0]);
        this.announce('Panned right');
        return true;

      // Zoom keys
      case '+':
      case '=':
        this.map.zoomIn();
        this.announce(`Zoomed in to level ${this.map.getZoom()}`);
        return true;

      case '-':
      case '_':
        this.map.zoomOut();
        this.announce(`Zoomed out to level ${this.map.getZoom()}`);
        return true;

      // Tab - cycle through features
      case 'Tab':
        if (e.shiftKey) {
          this.focusPreviousFeature();
        } else {
          this.focusNextFeature();
        }
        return true;

      // Enter or Space - activate focused feature
      case 'Enter':
      case ' ':
        this.activateFocusedFeature();
        return true;

      // Escape - close popup
      case 'Escape':
        this.map.closePopup();
        this.focusedFeatureIndex = -1;
        this.announce('Popup closed');
        return true;

      // Home - zoom to all features
      case 'Home':
        if (this.publicationsLayer.getBounds && this.publicationsLayer.getBounds().isValid()) {
          this.map.fitBounds(this.publicationsLayer.getBounds());
          this.announce('Zoomed to show all publications');
        }
        return true;

      default:
        return false;
    }
  }

  /**
   * Focus next feature in the list
   */
  focusNextFeature() {
    if (this.features.length === 0) {
      this.announce('No publications available');
      return;
    }

    this.focusedFeatureIndex = (this.focusedFeatureIndex + 1) % this.features.length;
    this.focusFeature(this.focusedFeatureIndex);
  }

  /**
   * Focus previous feature in the list
   */
  focusPreviousFeature() {
    if (this.features.length === 0) {
      this.announce('No publications available');
      return;
    }

    this.focusedFeatureIndex = (this.focusedFeatureIndex - 1 + this.features.length) % this.features.length;
    this.focusFeature(this.focusedFeatureIndex);
  }

  /**
   * Focus a specific feature
   */
  focusFeature(index) {
    if (index < 0 || index >= this.features.length) return;

    const featureData = this.features[index];
    const layer = featureData.layer;
    const properties = featureData.feature.properties;

    // Pan to feature
    if (layer.getBounds) {
      this.map.fitBounds(layer.getBounds(), { padding: [50, 50] });
    } else if (layer.getLatLng) {
      this.map.setView(layer.getLatLng(), Math.max(this.map.getZoom(), 10));
    }

    // Highlight feature
    if (this.interactionManager) {
      this.interactionManager.selectPublication(featureData);
    }

    // Announce feature
    const title = properties.title || 'Untitled publication';
    const doi = properties.doi || '';
    this.announce(`Publication ${index + 1} of ${this.features.length}: ${title}. Press Enter to view details.`);
  }

  /**
   * Activate the currently focused feature
   */
  activateFocusedFeature() {
    if (this.focusedFeatureIndex < 0 || this.focusedFeatureIndex >= this.features.length) {
      this.announce('No publication selected. Use Tab to select a publication.');
      return;
    }

    const featureData = this.features[this.focusedFeatureIndex];
    const layer = featureData.layer;

    // Get center point for popup
    let latlng;
    if (layer.getBounds) {
      latlng = layer.getBounds().getCenter();
    } else if (layer.getLatLng) {
      latlng = layer.getLatLng();
    }

    if (latlng && this.interactionManager) {
      // Check for overlapping features at this location
      const overlapping = this.interactionManager.findOverlappingFeatures(latlng);

      if (overlapping.length > 1) {
        this.interactionManager.showPaginatedPopup(overlapping, latlng);
        this.announce(`Multiple publications at this location. Use arrow buttons to navigate.`);
      } else {
        this.interactionManager.showPublicationPopup(featureData, latlng);
        this.announce('Publication details opened');
      }
    }
  }

  /**
   * Announce message to screen readers
   */
  announce(message) {
    // Find or create announcer element
    let announcer = document.getElementById('map-announcer');
    if (!announcer) {
      announcer = document.createElement('div');
      announcer.id = 'map-announcer';
      announcer.className = 'sr-only';
      announcer.setAttribute('role', 'status');
      announcer.setAttribute('aria-live', 'polite');
      announcer.setAttribute('aria-atomic', 'true');
      document.body.appendChild(announcer);
    }

    // Update message
    announcer.textContent = message;

    // Log for debugging
    console.log('Screen reader announcement:', message);
  }
}
