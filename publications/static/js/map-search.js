// publications/static/js/map-search.js
// Full-text search filtering for map publications

/**
 * Map Search Manager
 * Provides real-time filtering of publications on the map
 * - Searches across all text fields in publication data
 * - Minimum 3 characters to activate
 * - Debounced for performance
 * - Accessible with keyboard and screen readers
 */
class MapSearchManager {
  constructor(map, publicationsLayer, allPublications, publicationsGroup = null) {
    this.map = map;
    this.publicationsLayer = publicationsLayer;  // The GeoJSON layer
    this.publicationsGroup = publicationsGroup;  // The layer group (for layer control)

    // Extract features array from GeoJSON object if needed
    if (allPublications && allPublications.type === 'FeatureCollection') {
      this.allPublications = allPublications.features || [];
    } else if (Array.isArray(allPublications)) {
      this.allPublications = allPublications;
    } else {
      this.allPublications = [];
    }

    this.filteredPublications = [];
    this.filteredLayer = null;  // NEW: Separate layer for search results
    this.searchInput = null;
    this.searchButton = null;
    this.clearButton = null;
    this.searchContainer = null;
    this.searchForm = null;
    this.statusElement = null;
    this.searchTimeout = null;
    this.minSearchLength = 3;
    this.isSearchActive = false;
    this.searchStartTime = null;

    console.group('🔍 Map Search Initialization');
    console.log('Publications object type:', allPublications?.type || 'unknown');
    console.log('Total publications loaded:', this.allPublications.length);
    if (this.allPublications.length > 0) {
      console.log('Sample publication:', this.allPublications[0]);
    }
    this.init();
    console.groupEnd();
  }

  /**
   * Initialize search functionality
   */
  init() {
    // Find search elements
    this.searchInput = document.getElementById('map-search-input');
    this.searchButton = document.getElementById('search-submit-btn');
    this.clearButton = document.getElementById('clear-search-btn');
    this.searchContainer = document.getElementById('navbar-search-container');
    this.searchForm = document.querySelector('.navbar-search-form');
    this.statusElement = document.getElementById('search-results-status');

    console.log('Search elements found:', {
      input: !!this.searchInput,
      searchButton: !!this.searchButton,
      clearButton: !!this.clearButton,
      container: !!this.searchContainer,
      form: !!this.searchForm,
      statusElement: !!this.statusElement
    });

    if (!this.searchInput) {
      console.warn('⚠️ Map search input not found');
      return;
    }

    // Setup event listeners
    this.setupEventListeners();

    console.log(`✅ Map search initialized with ${this.allPublications.length} publications`);
  }

  /**
   * Check if we're on a map page
   */
  isMapPage() {
    // Check if map element exists
    return document.getElementById('map') !== null;
  }

  /**
   * Setup event listeners
   */
  setupEventListeners() {
    if (!this.searchInput) return;

    console.log('📋 Setting up event listeners...');

    // Form submit (Enter key)
    if (this.searchForm) {
      this.searchForm.addEventListener('submit', (e) => {
        e.preventDefault();
        console.log('📝 Form submitted (Enter key pressed)');
        const query = this.searchInput.value;
        if (query.trim().length >= this.minSearchLength) {
          // Clear debounce and search immediately
          if (this.searchTimeout) {
            clearTimeout(this.searchTimeout);
          }
          this.performSearch(query);
        } else {
          console.warn(`⚠️ Search query too short: "${query}" (minimum ${this.minSearchLength} characters)`);
        }
      });
    }

    // Search button click
    if (this.searchButton) {
      this.searchButton.addEventListener('click', (e) => {
        e.preventDefault();
        console.log('🔍 Search button clicked');
        const query = this.searchInput.value;
        if (query.trim().length >= this.minSearchLength) {
          // Clear debounce and search immediately
          if (this.searchTimeout) {
            clearTimeout(this.searchTimeout);
          }
          this.performSearch(query);
        } else {
          console.warn(`⚠️ Search query too short: "${query}" (minimum ${this.minSearchLength} characters)`);
        }
      });
    }

    // Input event with debouncing
    this.searchInput.addEventListener('input', (e) => {
      console.log(`⌨️ Input changed: "${e.target.value}"`);
      this.handleSearchInput(e.target.value);
    });

    // Keydown for special keys
    this.searchInput.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') {
        e.preventDefault();
        console.log('⎋ Escape key pressed - clearing search');
        this.clearSearch();
      }
    });

    // Clear button
    if (this.clearButton) {
      this.clearButton.addEventListener('click', () => {
        console.log('❌ Clear button clicked');
        this.clearSearch();
        this.searchInput.focus();
      });
    }

    // Focus events for accessibility
    this.searchInput.addEventListener('focus', () => {
      console.log('🎯 Search field focused');
      this.announce('Search field focused. Type at least 3 characters to filter publications.');
    });

    console.log('✅ Event listeners set up successfully');
  }

  /**
   * Handle search input with debouncing
   */
  handleSearchInput(query) {
    // Clear previous timeout
    if (this.searchTimeout) {
      clearTimeout(this.searchTimeout);
    }

    // Show/hide clear button
    if (this.clearButton) {
      this.clearButton.style.display = query.length > 0 ? 'block' : 'none';
    }

    // Debounce search
    this.searchTimeout = setTimeout(() => {
      this.performSearch(query);
    }, 300);
  }

  /**
   * Perform the actual search
   */
  performSearch(query) {
    this.searchStartTime = performance.now();
    const trimmedQuery = query.trim();

    console.group(`🔎 Performing Search`);
    console.log('Query:', `"${trimmedQuery}"`);
    console.log('Query length:', trimmedQuery.length);
    console.log('Minimum required:', this.minSearchLength);

    // Clear search if less than minimum length
    if (trimmedQuery.length < this.minSearchLength) {
      console.warn(`⚠️ Query too short (${trimmedQuery.length} < ${this.minSearchLength})`);
      if (this.isSearchActive) {
        console.log('Clearing active search...');
        this.showAllPublications();
        this.announce('Search cleared. Showing all publications.');
      }
      console.groupEnd();
      return;
    }

    // Add searching class for loading indicator
    if (this.searchInput) {
      this.searchInput.classList.add('searching');
    }

    // Perform the search
    const searchTerms = trimmedQuery.toLowerCase().split(/\s+/);
    console.log('Search terms:', searchTerms);
    console.log('Total publications to search:', this.allPublications.length);

    const filterStartTime = performance.now();
    this.filteredPublications = this.allPublications.filter(pub => {
      return this.matchesSearch(pub, searchTerms);
    });
    const filterTime = performance.now() - filterStartTime;

    console.log(`⏱️ Filtering took: ${filterTime.toFixed(2)}ms`);
    console.log(`📊 Results: ${this.filteredPublications.length} / ${this.allPublications.length}`);

    // Log sample of matched publications
    if (this.filteredPublications.length > 0) {
      console.log('Sample matches (first 3):');
      this.filteredPublications.slice(0, 3).forEach((pub, index) => {
        console.log(`  ${index + 1}. ${pub.properties?.title || 'Untitled'}`);
      });
    }

    // Update map
    const mapUpdateStart = performance.now();
    this.updateMap();
    const mapUpdateTime = performance.now() - mapUpdateStart;
    console.log(`🗺️ Map update took: ${mapUpdateTime.toFixed(2)}ms`);

    // Remove searching class
    if (this.searchInput) {
      setTimeout(() => {
        this.searchInput.classList.remove('searching');
      }, 300);
    }

    // Announce results
    const count = this.filteredPublications.length;
    const total = this.allPublications.length;
    const percentage = ((count / total) * 100).toFixed(1);
    const totalTime = performance.now() - this.searchStartTime;

    const message = count === 1
      ? `1 publication found matching "${trimmedQuery}"`
      : `${count} publications found matching "${trimmedQuery}" (${percentage}% of total)`;

    console.log(`✅ ${message}`);
    console.log(`⏱️ Total search time: ${totalTime.toFixed(2)}ms`);
    console.groupEnd();

    this.announce(message);

    this.isSearchActive = true;
  }

  /**
   * Check if publication matches search terms
   * Searches across all text fields in the publication
   */
  matchesSearch(publication, searchTerms) {
    if (!publication) return false;

    // Build searchable text from all fields
    const searchableText = this.buildSearchableText(publication);

    // Check if all search terms are found
    return searchTerms.every(term => searchableText.includes(term));
  }

  /**
   * Build searchable text from publication object
   * Includes all text fields from the API response
   */
  buildSearchableText(pub) {
    const parts = [];

    // GeoJSON properties (primary source of data)
    if (pub.properties) {
      const props = pub.properties;

      // Title
      if (props.title) parts.push(props.title);

      // DOI
      if (props.doi) parts.push(props.doi);

      // Abstract
      if (props.abstract) parts.push(props.abstract);

      // Authors (array of strings)
      if (Array.isArray(props.authors)) {
        parts.push(...props.authors);
      }

      // Keywords (array of strings)
      if (Array.isArray(props.keywords)) {
        parts.push(...props.keywords);
      }

      // Topics (array of objects with display_name)
      if (Array.isArray(props.topics)) {
        props.topics.forEach(topic => {
          if (topic.display_name) parts.push(topic.display_name);
          if (topic.subfield) parts.push(topic.subfield);
          if (topic.field) parts.push(topic.field);
          if (topic.domain) parts.push(topic.domain);
        });
      }

      // Source details
      if (props.source_details) {
        const source = props.source_details;
        if (source.name) parts.push(source.name);
        if (source.display_name) parts.push(source.display_name);
        if (source.abbreviated_title) parts.push(source.abbreviated_title);
        if (source.publisher_name) parts.push(source.publisher_name);
        if (source.issn_l) parts.push(source.issn_l);
      }

      // URL
      if (props.url) parts.push(props.url);

      // OpenAlex ID
      if (props.openalex_id) parts.push(props.openalex_id);

      // PMID, PMCID
      if (props.pmid) parts.push(props.pmid);
      if (props.pmcid) parts.push(props.pmcid);

      // Time period
      if (props.timeperiod_startdate) parts.push(props.timeperiod_startdate);
      if (props.timeperiod_enddate) parts.push(props.timeperiod_enddate);

      // Region description
      if (props.region_description) parts.push(props.region_description);
    }

    // Join all parts and convert to lowercase
    return parts.join(' ').toLowerCase();
  }

  /**
   * Update map to show only filtered publications
   * Uses layer replacement strategy for clean display
   */
  updateMap() {
    if (!this.map) return;

    console.log('🗺️ Updating map display...');
    console.log('Filtered publications count:', this.filteredPublications.length);

    // Remove existing filtered layer if any
    if (this.filteredLayer) {
      this.map.removeLayer(this.filteredLayer);

      // Remove from layer control if present
      if (window.mapLayerControl) {
        window.mapLayerControl.removeLayer(this.filteredLayer);
      }

      this.filteredLayer = null;
      console.log('🗑️ Removed previous filtered layer');
    }

    // Hide the original publications layer
    if (this.publicationsGroup && this.map.hasLayer(this.publicationsGroup)) {
      this.map.removeLayer(this.publicationsGroup);
      console.log('👻 Hid original "All works" layer');
    }

    // Create a new GeoJSON FeatureCollection with filtered publications
    const filteredGeoJSON = {
      type: 'FeatureCollection',
      features: this.filteredPublications
    };

    console.log('📦 Creating filtered layer with', this.filteredPublications.length, 'features');

    // Import the style and popup functions from the global scope
    const styleFunc = window.publicationStyle || this.publicationsLayer.options.style;
    const popupFunc = window.publicationPopup || this.publicationsLayer.options.onEachFeature;

    // Create a new layer with the filtered publications
    this.filteredLayer = L.geoJSON(filteredGeoJSON, {
      style: styleFunc,
      onEachFeature: popupFunc
    });

    // Add the filtered layer to the map
    this.filteredLayer.addTo(this.map);
    console.log('✅ Added filtered layer to map');

    // Add to layer control
    if (window.mapLayerControl) {
      const resultCount = this.filteredPublications.length;
      const layerName = `Search results (${resultCount})`;
      window.mapLayerControl.addOverlay(this.filteredLayer, layerName);
      console.log('📋 Added to layer control as:', layerName);
    }

    // Fit map to filtered results
    if (this.filteredPublications.length > 0) {
      const bounds = this.filteredLayer.getBounds();
      if (bounds.isValid()) {
        this.map.fitBounds(bounds, { padding: [50, 50] });
        console.log('🗺️ Map fitted to filtered results');
      }
    }
  }

  /**
   * Show all publications (clear filter)
   * Removes filtered layer and restores original layer
   */
  showAllPublications() {
    if (!this.map) return;

    console.log('🗺️ Showing all publications...');

    // Remove filtered layer if it exists
    if (this.filteredLayer) {
      this.map.removeLayer(this.filteredLayer);

      // Remove from layer control
      if (window.mapLayerControl) {
        window.mapLayerControl.removeLayer(this.filteredLayer);
        console.log('📋 Removed from layer control');
      }

      this.filteredLayer = null;
      console.log('🗑️ Removed filtered layer');
    }

    // Restore the original publications layer
    if (this.publicationsGroup && !this.map.hasLayer(this.publicationsGroup)) {
      this.publicationsGroup.addTo(this.map);
      console.log('✅ Restored original "All works" layer');
    }

    // Fit to all publications
    if (this.publicationsGroup) {
      const bounds = this.publicationsGroup.getBounds();
      if (bounds.isValid()) {
        this.map.fitBounds(bounds);
        console.log('🗺️ Map fitted to all publications');
      }
    }

    this.filteredPublications = [];
    this.isSearchActive = false;
  }

  /**
   * Clear search
   */
  clearSearch() {
    if (this.searchInput) {
      this.searchInput.value = '';
    }

    if (this.clearButton) {
      this.clearButton.style.display = 'none';
    }

    this.showAllPublications();
    this.announce('Search cleared. Showing all publications.');
  }

  /**
   * Announce message to screen readers
   */
  announce(message) {
    if (!this.statusElement) {
      // Try to find or create status element
      this.statusElement = document.getElementById('search-results-status');
      if (!this.statusElement) {
        this.statusElement = document.createElement('div');
        this.statusElement.id = 'search-results-status';
        this.statusElement.className = 'sr-only';
        this.statusElement.setAttribute('role', 'status');
        this.statusElement.setAttribute('aria-live', 'polite');
        this.statusElement.setAttribute('aria-atomic', 'true');
        document.body.appendChild(this.statusElement);
      }
    }

    this.statusElement.textContent = message;
    console.log('Screen reader announcement:', message);
  }

  /**
   * Update publications data (called when new data is loaded)
   */
  updatePublications(publications) {
    this.allPublications = publications || [];
    console.log(`Map search updated with ${this.allPublications.length} publications`);

    // If search is active, re-run search
    if (this.isSearchActive && this.searchInput && this.searchInput.value.trim().length >= this.minSearchLength) {
      this.performSearch(this.searchInput.value);
    }
  }
}
