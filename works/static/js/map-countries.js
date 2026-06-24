// SPDX-FileCopyrightText: 2026 OPTIMETA and KOMET projects <https://projects.tib.eu/komet>
// SPDX-License-Identifier: GPL-3.0-or-later

// map-countries.js
// Manages a toggleable countries (national borders) layer on the map (#29).
// Mirrors MapGlobalRegionsManager: outlines only, non-interactive, off by
// default, lazily fetched from /api/v1/countries/.

class MapCountriesManager {
  constructor(map, layerControl) {
    this.map = map;
    this.layerControl = layerControl;
    this.countriesLayer = null;
    this.apiUrl = '/api/v1/countries/';
    this.init();
  }

  async init() {
    try {
      this.countriesLayer = L.featureGroup();
      this.layerControl.addOverlay(this.countriesLayer, 'Countries');

      const response = await fetch(this.apiUrl);
      const data = await response.json();

      let countries;
      if (data.results && data.results.type === 'FeatureCollection') {
        countries = data.results.features;
      } else if (data.results && Array.isArray(data.results)) {
        countries = data.results;
      } else if (data.features && Array.isArray(data.features)) {
        countries = data.features;
      } else if (Array.isArray(data)) {
        countries = data;
      } else {
        console.error('Unexpected /api/v1/countries/ response format:', data);
        return;
      }

      const geoJsonLayer = L.geoJSON(countries, {
        style: this.getCountryStyle.bind(this),
        interactive: false,
      });
      geoJsonLayer.eachLayer((layer) => this.countriesLayer.addLayer(layer));

      console.log(`Countries layer loaded (${countries.length} countries, disabled by default)`);
    } catch (error) {
      console.error('Failed to load countries layer:', error);
    }
  }

  getCountryStyle() {
    return {
      color: '#555',
      weight: 1,
      opacity: 0.6,
      fillOpacity: 0.0,
      interactive: false,
      bubblingMouseEvents: false,
    };
  }
}
