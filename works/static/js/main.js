// SPDX-FileCopyrightText: 2022 OPTIMETA and KOMET projects <https://projects.tib.eu/komet>
// SPDX-License-Identifier: GPL-3.0-or-later

// publications/static/js/main.js

// Leaflet map initialization with chunked loading of publication geometries.
// Full popup details are fetched lazily (see map-popup.js).

// 2. Once the DOM is ready, initialize the map
$(document).ready(function() {
  initMap();
});

// API URL and copyright attribution
const dataCopyright =
  " | Publication metadata license: <a href='https://creativecommons.org/publicdomain/zero/1.0/'>CC-0</a>";

async function initMap() {
  // main.html is also extended by non-map pages (about, privacy, data, …) that
  // do not override {% block scripts %}, so this script runs there too. Bail
  // out gracefully when there is no #map element to initialise.
  const mapEl = document.getElementById('map');
  if (!mapEl) {
    return;
  }
  const { map, tileLayer: osmLayer } = createBaseMap(mapEl, {}, {
    attribution: OPTIMAP_OSM_ATTR + dataCopyright,
  });
  window._optimapMap = map;

  // Controls: scale and layer switcher. The work overlays are added by
  // MapStatusLayersManager once the data has loaded so that the layer-control
  // labels reflect the actual published / unpublished split.
  L.control.scale({ position: 'bottomright' }).addTo(map);
  const layerControl = L.control
    .layers({ 'OpenStreetMap': osmLayer }, {})
    .addTo(map);

  // Make layer control globally available for search manager
  window.mapLayerControl = layerControl;

  // Make style and popup functions globally available for search manager
  window.publicationStyle = publicationStyle;
  window.publicationPopup = publicationPopup;

  // -------------------------------------------------------------------------
  // Chunked loading
  // -------------------------------------------------------------------------
  const CHUNK_SIZE = window.OPTIMAP_SETTINGS?.mapChunkSize ?? 1000;
  const MAP_API_BASE = '/api/v1/works/?minimal=true';

  // Pre-fetch statistics: used for (a) the loading-indicator denominator and
  // (b) layer-control labels.  `total_works_for_user` is auth-aware.
  let totalForUser = null;
  let publishedLabel    = 'Published works';
  let unpublishedLabel  = 'Unpublished works';
  try {
    const statsResp = await fetch('/api/v1/statistics/');
    if (statsResp.ok) {
      const stats = await statsResp.json();
      totalForUser = stats.total_works_for_user ?? stats.published_works ?? null;

      const nPublished   = stats.published_works ?? null;
      // Unpublished = everything the works API returns for this user minus published.
      const nUnpublished = (totalForUser !== null && nPublished !== null && totalForUser > nPublished)
        ? totalForUser - nPublished
        : null;

      if (nPublished   !== null) publishedLabel   = `Published works (${nPublished.toLocaleString()})`;
      if (nUnpublished !== null) unpublishedLabel  = `Unpublished works (${nUnpublished.toLocaleString()})`;
    }
  } catch (_) {}

  const loadingEl = document.getElementById('map-loading-status');

  // Show indicator immediately with the pre-fetched total (before first chunk arrives).
  if (loadingEl && totalForUser !== null) {
    loadingEl.style.display = 'block';
    loadingEl.textContent = `Loading works… 0 / ${totalForUser}`;
  }

  let statusLayers = null;
  let pubsLayer    = null;
  let pubsGroup    = null;
  let searchManager = null;
  let offset = 0;
  let serverTotal = Infinity;

  while (offset < serverTotal) {
    const url = `${MAP_API_BASE}&limit=${CHUNK_SIZE}&offset=${offset}`;
    let body;
    try {
      const resp = await fetch(url);
      body = await resp.json();
    } catch (err) {
      console.error('OPTIMAP: failed to fetch works chunk', err);
      break;
    }

    serverTotal = body.count ?? 0;
    // GeoFeatureModelSerializer wraps results as a FeatureCollection object.
    // LimitOffsetPagination puts it under `results`; extract the features array.
    const rawResults = body.results;
    const featureCollection = (rawResults && typeof rawResults === 'object' && !Array.isArray(rawResults))
      ? rawResults
      : { type: 'FeatureCollection', features: Array.isArray(rawResults) ? rawResults : [] };
    const features = featureCollection.features ?? [];
    if (!features.length) break;

    offset += features.length;

    // Update loading indicator: use serverTotal (from body.count) as the true denominator;
    // fall back to the pre-fetched estimate only before the first response arrives.
    if (loadingEl) {
      loadingEl.style.display = 'block';
      const shown = serverTotal !== Infinity ? serverTotal : (totalForUser ?? '?');
      loadingEl.textContent = `Loading works… ${offset} / ${shown}`;
    }

    if (statusLayers === null) {
      // First chunk: initialise all managers.
      // Pass the full FeatureCollection so L.geoJSON and MapSearchManager
      // can each normalise it as they see fit.
      console.log(`OPTIMAP: loading ${serverTotal} works in chunks of ${CHUNK_SIZE}`);
      statusLayers = new MapStatusLayersManager(map, layerControl, featureCollection, {
        publishedLabel,
        unpublishedLabel,
      });
      pubsLayer    = statusLayers.getCombinedLayer();
      pubsGroup    = statusLayers.getPublicationsGroup();
      window.mapStatusLayersManager = statusLayers;

      // Initialize enhanced interaction manager for handling overlapping polygons
      if (typeof MapInteractionManager !== 'undefined') {
        const interactionManager = new MapInteractionManager(map, pubsLayer);
        console.log('Enhanced map interaction enabled');

        // Initialize keyboard navigation for accessibility
        if (typeof MapKeyboardNavigation !== 'undefined') {
          new MapKeyboardNavigation(map, pubsLayer, interactionManager);
          console.log('Keyboard navigation enabled');
        }
      }

      // Initialize map search functionality
      if (typeof MapSearchManager !== 'undefined') {
        searchManager = new MapSearchManager(map, pubsLayer, features, pubsGroup);
        window.mapSearchManager = searchManager;
        console.log('Map search enabled');
      }

      // Initialize gazetteer (location search)
      if (typeof MapGazetteerManager !== 'undefined' && window.OPTIMAP_SETTINGS?.gazetteer) {
        const gazetteerManager = new MapGazetteerManager(map, window.OPTIMAP_SETTINGS.gazetteer);
        window.mapGazetteerManager = gazetteerManager;
        console.log('Gazetteer enabled');
      }

      // Initialize zoom to all features control
      if (typeof MapZoomToAllControl !== 'undefined') {
        window.mapZoomToAllControl = new MapZoomToAllControl(map, pubsGroup);
        console.log('Zoom to all features control enabled');
      }

      // Initialize global regions layer
      if (typeof MapGlobalRegionsManager !== 'undefined') {
        window.mapGlobalRegionsManager = new MapGlobalRegionsManager(map, layerControl);
        console.log('Global regions layer initialized');
      }

      // Fit to first chunk immediately so the user sees content fast.
      if (pubsGroup.getBounds().isValid()) {
        map.fitBounds(pubsGroup.getBounds());
      }
    } else {
      // Subsequent chunks: add to existing layers.
      statusLayers.addFeatures(features);
      searchManager?.addPublications(features);
    }
  }

  if (loadingEl) loadingEl.style.display = 'none';
  console.log(`OPTIMAP: finished loading ${offset} works.`);
}

// Note: publicationPopup and publicationStyle functions are imported from map-popup.js
