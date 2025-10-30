// map-global-regions.js
// Manages global regions (continents and oceans) layer on the map

class MapGlobalRegionsManager {
  constructor(map, layerControl) {
    this.map = map;
    this.layerControl = layerControl;
    this.regionsLayer = null;
    this.labelsLayer = null;
    this.apiUrl = '/api/v1/global-regions/';

    // Create custom pane for region labels with high z-index
    if (!this.map.getPane('regionLabels')) {
      const labelsPane = this.map.createPane('regionLabels');
      labelsPane.style.zIndex = 650; // Above overlays (400) and shadows (500), below popups (700)
      labelsPane.style.pointerEvents = 'none'; // Don't interfere with map interactions
    }

    // Initialize asynchronously
    this.init();
  }

  async init() {
    try {
      // Create empty layer group first and add to control immediately
      this.regionsLayer = L.featureGroup();
      this.labelsLayer = L.featureGroup();

      // Add to layer control (turned off by default)
      // We'll control both layers together through the regions layer
      this.layerControl.addOverlay(this.regionsLayer, 'Global regions');

      // Listen for layer add/remove to sync labels
      this.map.on('overlayadd', (e) => {
        if (e.layer === this.regionsLayer && this.labelsLayer) {
          this.map.addLayer(this.labelsLayer);
        }
      });

      this.map.on('overlayremove', (e) => {
        if (e.layer === this.regionsLayer && this.labelsLayer) {
          this.map.removeLayer(this.labelsLayer);
        }
      });

      // Fetch global regions from API
      const response = await fetch(this.apiUrl);
      const data = await response.json();

      console.log('Global regions API response:', data);

      // Handle different response formats:
      // 1. Paginated GeoJSON: data.results is a FeatureCollection
      // 2. Direct GeoJSON FeatureCollection: data.features
      // 3. Array of features
      let regions;

      if (data.results && data.results.type === 'FeatureCollection') {
        // Paginated response with GeoJSON FeatureCollection in results
        regions = data.results.features;
      } else if (data.results && Array.isArray(data.results)) {
        // Paginated response with array of features
        regions = data.results;
      } else if (data.features && Array.isArray(data.features)) {
        // Direct GeoJSON FeatureCollection
        regions = data.features;
      } else if (Array.isArray(data)) {
        // Direct array of features
        regions = data;
      } else {
        console.error('Unexpected API response format:', data);
        return;
      }

      console.log(`Loaded ${regions.length} global regions`);

      // Add GeoJSON features to the layer group
      const geoJsonLayer = L.geoJSON(regions, {
        style: this.getRegionStyle.bind(this),
        onEachFeature: this.onEachRegion.bind(this),
        // Disable interaction
        interactive: false
      });

      // Add all features to the regions layer
      geoJsonLayer.eachLayer((layer) => {
        this.regionsLayer.addLayer(layer);
      });

      // Add labels for each region
      regions.forEach(feature => {
        this.addRegionLabel(feature);
      });

      console.log('Global regions layer loaded (disabled by default)');
    } catch (error) {
      console.error('Failed to load global regions:', error);
    }
  }

  getRegionStyle(feature) {
    // High opacity outline with dashed line, minimal fill
    const regionType = feature.properties.region_type;

    // Different colors for continents vs oceans
    const color = regionType === 'C' ? '#8B4513' : '#1E90FF'; // Brown for continents, blue for oceans

    return {
      color: color,
      weight: 2,
      opacity: 0.7,
      fillOpacity: 0.05,
      fillColor: color,
      dashArray: '5, 10', // Dashed line pattern: 5px dash, 10px gap
      // Ensure layer is non-interactive
      interactive: false,
      bubblingMouseEvents: false
    };
  }

  onEachRegion() {
    // No popup or interaction - layer is purely visual reference
    // Layer is already set to non-interactive in the geoJSON options
  }

  addRegionLabel(feature) {
    // Calculate the center of the region's bounding box
    const bounds = L.geoJSON(feature).getBounds();
    const center = bounds.getCenter();

    // Create a custom divIcon with medium-sized bold text
    const labelIcon = L.divIcon({
      className: 'region-label',
      html: `<div style="
        font-size: 16px;
        font-weight: bold;
        color: ${feature.properties.region_type === 'C' ? '#8B4513' : '#1E90FF'};
        opacity: 0.6;
        text-shadow:
          -0.5px -0.5px 0 rgba(255,255,255,0.7),
           0.5px -0.5px 0 rgba(255,255,255,0.7),
          -0.5px  0.5px 0 rgba(255,255,255,0.7),
           0.5px  0.5px 0 rgba(255,255,255,0.7),
           1px 1px 2px rgba(0,0,0,0.2);
        white-space: nowrap;
        pointer-events: none;
        text-align: center;
      ">${feature.properties.name}</div>`,
      iconSize: null,
      iconAnchor: null
    });

    // Create marker at center with the label in custom pane
    const labelMarker = L.marker(center, {
      icon: labelIcon,
      interactive: false,
      keyboard: false,
      bubblingMouseEvents: false,
      pane: 'regionLabels' // Use custom pane with high z-index
    });

    // Add label to the labels layer (separate from regions layer)
    this.labelsLayer.addLayer(labelMarker);
  }
}
