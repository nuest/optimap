// publications/static/js/map-gazetteer.js
// Gazetteer (location search) functionality for the map

/**
 * Map Gazetteer Manager
 * Provides location search using configurable geocoding providers
 * - Separate from publication search (doesn't filter publications)
 * - Pans/zooms map to searched location
 * - Supports multiple geocoding services (Nominatim, Photon, etc.)
 */
class MapGazetteerManager {
  constructor(map, options = {}) {
    this.map = map;
    this.provider = options.provider || 'nominatim';
    this.placeholder = options.placeholder || 'Search for a location...';
    this.geocoder = null;

    console.group('📍 Map Gazetteer Initialization');
    console.log('Provider:', this.provider);
    console.log('Placeholder:', this.placeholder);
    
    this.init();
    console.groupEnd();
  }

  /**
   * Initialize the geocoder control
   */
  init() {
    if (!this.map) {
      console.warn('⚠️ Map not found, cannot initialize gazetteer');
      return;
    }

    if (typeof L === 'undefined' || !L.Control || !L.Control.Geocoder) {
      console.warn('⚠️ Leaflet Control Geocoder not loaded, cannot initialize gazetteer');
      return;
    }

    // Get the geocoder instance based on provider
    const geocoderInstance = this.getGeocoderInstance();

    if (!geocoderInstance) {
      console.warn('⚠️ Unknown geocoder provider:', this.provider);
      return;
    }

    // Create the geocoder control
    this.geocoder = L.Control.geocoder({
      geocoder: geocoderInstance,
      placeholder: this.placeholder,
      defaultMarkGeocode: false, // Custom handling
      position: 'topleft',
      collapsed: true,
      errorMessage: 'No location found',
    });

    // Add custom handler for geocoding results
    this.geocoder.on('markgeocode', (e) => {
      this.handleGeocode(e);
    });

    // Add to map
    this.geocoder.addTo(this.map);

    // Add accessibility attributes to the geocoder button
    this.addAccessibilityAttributes();

    console.log('✅ Gazetteer initialized with', this.provider);
  }

  /**
   * Add accessibility attributes to the geocoder button
   */
  addAccessibilityAttributes() {
    // Wait for DOM to be ready
    setTimeout(() => {
      const geocoderButton = document.querySelector('.leaflet-control-geocoder-icon');
      if (geocoderButton) {
        geocoderButton.setAttribute('title', 'Search locations on the map');
        geocoderButton.setAttribute('aria-label', 'Search locations on the map');
        console.log('✅ Added accessibility attributes to gazetteer button');
      } else {
        console.warn('⚠️ Could not find geocoder button to add accessibility attributes');
      }
    }, 100);
  }

  /**
   * Get geocoder instance based on provider name
   */
  getGeocoderInstance() {
    const provider = this.provider.toLowerCase();

    switch (provider) {
      case 'nominatim':
        // Use built-in Nominatim geocoder with proxy
        // Need full URL (with protocol and host) for URL constructor
        const nominatimUrl = `${window.location.origin}/api/v1/gazetteer/nominatim/`;
        console.log('Using built-in Nominatim geocoder with proxy URL:', nominatimUrl);
        return L.Control.Geocoder.nominatim({
          serviceUrl: nominatimUrl,
          geocodingQueryParams: {
            format: 'json',
            addressdetails: 1
          }
        });

      case 'photon':
        // Use built-in Photon geocoder with proxy
        const photonUrl = `${window.location.origin}/api/v1/gazetteer/photon/`;
        console.log('Using built-in Photon geocoder with proxy URL:', photonUrl);
        return L.Control.Geocoder.photon({
          serviceUrl: photonUrl
        });

      default:
        console.warn('⚠️ Unknown geocoder provider:', provider);
        return null;
    }
  }

  /**
   * Handle geocoding result
   * Pans to location and adds temporary marker
   */
  handleGeocode(e) {
    const result = e.geocode;
    const latlng = result.center;

    console.group('📍 Gazetteer Result');
    console.log('Name:', result.name);
    console.log('Location:', latlng);
    console.log('Bounds:', result.bbox);
    console.groupEnd();

    // Fit to bounds if available, otherwise pan to point
    if (result.bbox) {
      const bbox = result.bbox;
      const bounds = L.latLngBounds(
        L.latLng(bbox.getSouth(), bbox.getWest()),
        L.latLng(bbox.getNorth(), bbox.getEast())
      );
      this.map.fitBounds(bounds, { maxZoom: 16 });
    } else {
      this.map.setView(latlng, 13);
    }

    // Add temporary marker that disappears after 5 seconds
    const marker = L.marker(latlng, {
      icon: L.divIcon({
        className: 'gazetteer-marker',
        html: '<i class="fas fa-map-marker-alt" style="color: #FF6B35; font-size: 32px;"></i>',
        iconSize: [32, 32],
        iconAnchor: [16, 32],
      })
    })
      .addTo(this.map)
      .bindPopup(result.name)
      .openPopup();

    // Remove marker after 5 seconds
    setTimeout(() => {
      this.map.removeLayer(marker);
      console.log('🗑️ Temporary gazetteer marker removed');
    }, 5000);
  }

  /**
   * Programmatically search for a location
   */
  search(query) {
    if (!this.geocoder) {
      console.warn('⚠️ Gazetteer not initialized');
      return;
    }

    console.log('🔍 Searching for location:', query);

    const geocoderInstance = this.geocoder.options.geocoder;
    geocoderInstance.geocode(query, (results) => {
      if (results && results.length > 0) {
        console.log(`📍 Found ${results.length} location(s)`);
        const result = results[0];
        this.handleGeocode({ geocode: result });
      } else {
        console.warn('⚠️ No location found for query:', query);
      }
    });
  }
}

// Make available globally
window.MapGazetteerManager = MapGazetteerManager;
