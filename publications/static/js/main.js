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
const publications_url = '/api/v1/publications/?limit=999999';
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
  L.control
    .layers(
      { 'OpenStreetMap': osmLayer },
      { Publications: publicationsGroup }
    )
    .addTo(map);

  // Fetch data and add to map
  const pubs = await load_publications();
  const pubsLayer = L.geoJSON(pubs, {
    style: publicationStyle,
    onEachFeature: publicationPopup
  });
  pubsLayer.eachLayer((layer) => publicationsGroup.addLayer(layer));

  // Initialize enhanced interaction manager for handling overlapping polygons
  if (typeof MapInteractionManager !== 'undefined') {
    const interactionManager = new MapInteractionManager(map, pubsLayer);
    console.log('Enhanced map interaction enabled: overlapping polygon selection and geometry highlighting');
  }
  // Initialize gazetteer (location search)
  if (typeof MapGazetteerManager !== 'undefined' && window.OPTIMAP_SETTINGS?.gazetteer) {
    const gazetteerManager = new MapGazetteerManager(map, window.OPTIMAP_SETTINGS.gazetteer);
    console.log('Gazetteer enabled');

    // Make gazetteer manager globally available
    window.mapGazetteerManager = gazetteerManager;
  }


  // Fit map to markers
  if (publicationsGroup.getBounds().isValid()) {
    map.fitBounds(publicationsGroup.getBounds());
  }
}

// Note: publicationPopup and publicationStyle functions are imported from map-popup.js
