// SPDX-FileCopyrightText: 2026 OPTIMETA and KOMET projects <https://projects.tib.eu/komet>
// SPDX-License-Identifier: GPL-3.0-or-later

// map-countries.js
// Manages a toggleable countries (national borders) layer on the map (#29).
// Mirrors MapGlobalRegionsManager: outlines only, non-interactive, off by
// default. Country data is loaded (and browser-cached) via the shared
// OptimapCountries loader in countries-cache.js, which must be loaded first.

class MapCountriesManager {
  constructor(map, layerControl) {
    this.map = map;
    this.layerControl = layerControl;
    this.countriesLayer = null;
    this.init();
  }

  async init() {
    try {
      this.countriesLayer = L.featureGroup();
      this.layerControl.addOverlay(this.countriesLayer, 'Countries');

      const countries = await window.OptimapCountries.loadCountryFeatures();
      if (!countries || !countries.length) return;

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
