// publications/static/js/main.js

// Leaflet map initialization and popup rendering for publication points

// 1. Load all publications from the API
async function load_publications() {
  const response = await fetch(publications_url);
  const body = await response.json();
  console.log(`OPTIMAP retrieved ${body.count} results.`);
  return body.results;
}

// 2. Once the DOM is ready, initialize the map
$(document).ready(function() {
  initMap();
});

// API URL and copyright attribution
const publications_url = '/api/v1/works/?limit=999999';
const dataCopyright =
  " | Publication metadata license: <a href='https://creativecommons.org/publicdomain/zero/1.0/'>CC-0</a>";

async function initMap() {
  const map = L.map('map');

  // Base layer: OpenStreetMap
  const osmLayer = L.tileLayer(
    'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',
    {
      attribution:
        'Map data: © <a href="https://openstreetmap.org">OpenStreetMap</a> contributors' +
        dataCopyright,
      maxZoom: 18,
    }
  ).addTo(map);

  // Group to hold all publication markers
  const publicationsGroup = new L.FeatureGroup().addTo(map);

  // Controls: scale and layer switcher
  L.control.scale({ position: 'bottomright' }).addTo(map);
  const layerControl = L.control
    .layers(
      { 'OpenStreetMap': osmLayer },
      { 'All works': publicationsGroup }
    )
    .addTo(map);

  // Make layer control globally available for search manager
  window.mapLayerControl = layerControl;

  // Fetch data and add to map
  const pubs = await load_publications();
  const pubsLayer = L.geoJSON(pubs, {
    style: publicationStyle,
    onEachFeature: publicationPopup
  });
  pubsLayer.eachLayer((layer) => publicationsGroup.addLayer(layer));

  // Make style and popup functions globally available for search manager
  window.publicationStyle = publicationStyle;
  window.publicationPopup = publicationPopup;

  // Initialize enhanced interaction manager for handling overlapping polygons
  let interactionManager = null;
  if (typeof MapInteractionManager !== 'undefined') {
    interactionManager = new MapInteractionManager(map, pubsLayer);
    console.log('Enhanced map interaction enabled: overlapping polygon selection and geometry highlighting');
  }

  // Initialize keyboard navigation for accessibility
  if (typeof MapKeyboardNavigation !== 'undefined' && interactionManager) {
    const keyboardNav = new MapKeyboardNavigation(map, pubsLayer, interactionManager);
    console.log('Keyboard navigation enabled for accessibility');
  }

  // Initialize map search functionality
  if (typeof MapSearchManager !== 'undefined') {
    const searchManager = new MapSearchManager(map, pubsLayer, pubs, publicationsGroup);
    console.log('Map search enabled');

    // Make search manager globally available for potential use by other components
    window.mapSearchManager = searchManager;
  }

  // Initialize gazetteer (location search)
  if (typeof MapGazetteerManager !== 'undefined' && window.OPTIMAP_SETTINGS?.gazetteer) {
    const gazetteerManager = new MapGazetteerManager(map, window.OPTIMAP_SETTINGS.gazetteer);
    console.log('Gazetteer enabled');

    // Make gazetteer manager globally available
    window.mapGazetteerManager = gazetteerManager;
  }

  // Initialize zoom to all features control
  if (typeof MapZoomToAllControl !== 'undefined') {
    const zoomToAllControl = new MapZoomToAllControl(map, publicationsGroup);
    console.log('Zoom to all features control enabled');

    // Make zoom control globally available
    window.mapZoomToAllControl = zoomToAllControl;
  }

  // Initialize global regions layer
  if (typeof MapGlobalRegionsManager !== 'undefined') {
    const globalRegionsManager = new MapGlobalRegionsManager(map, layerControl);
    console.log('Global regions layer initialized');

    // Make global regions manager globally available
    window.mapGlobalRegionsManager = globalRegionsManager;
  }

  // Fit map to markers
  if (publicationsGroup.getBounds().isValid()) {
    map.fitBounds(publicationsGroup.getBounds());
  }
}

// Note: publicationPopup and publicationStyle functions are imported from map-popup.js
