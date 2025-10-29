// publications/static/js/map-interaction.js
// Enhanced map interaction for handling overlapping polygons and geometry highlighting

/**
 * Enhanced map interaction manager
 * Handles:
 * - Selection of overlapping polygons
 * - Cycling through features at the same location
 * - Highlighting all geometries belonging to the same publication
 */
class MapInteractionManager {
  constructor(map, publicationsLayer) {
    this.map = map;
    this.publicationsLayer = publicationsLayer;
    this.highlightedLayers = [];
    this.selectedPublication = null;
    this.overlappingFeatures = [];
    this.currentPageIndex = 0;
    this.paginatedPopup = null;
    this.currentClickLocation = null;

    // Style definitions
    this.defaultStyle = {
      color: '#158F9B',
      weight: 2,
      fillOpacity: 0.3,
    };

    this.highlightStyle = {
      color: '#FF4500',      // Bright red-orange for high contrast
      weight: 5,             // Thicker border
      fillOpacity: 0.6,      // More opaque
      fillColor: '#FF6B35',  // Explicit fill color
    };

    this.selectedStyle = {
      color: '#FFD700',      // Gold/yellow for maximum contrast
      weight: 6,             // Extra thick border
      fillOpacity: 0.7,      // Higher opacity
      fillColor: '#FFA500',  // Orange fill
      dashArray: '10, 5'     // More prominent dashes
    };

    this.initializeInteraction();
  }

  /**
   * Initialize click handlers for all layers
   */
  initializeInteraction() {
    // Store reference to this for use in event handlers
    const self = this;

    // Add click handler to each layer
    this.publicationsLayer.eachLayer((layer) => {
      layer.on('click', function(e) {
        // Prevent map click from firing
        L.DomEvent.stopPropagation(e);

        // Find all features at this location
        const clickedPoint = e.latlng;

        // Debug logging
        console.log('Click event latlng:', clickedPoint);

        const overlapping = self.findOverlappingFeatures(clickedPoint);

        if (overlapping.length === 0) {
          return;
        }

        if (overlapping.length === 1) {
          // Single feature - select it directly and show its popup
          self.selectPublication(overlapping[0]);
          self.showPublicationPopup(overlapping[0], clickedPoint);
        } else {
          // Multiple features - show paginated popup
          console.log('Showing paginated popup at:', clickedPoint);
          self.showPaginatedPopup(overlapping, clickedPoint);
        }
      });

      // Add hover effect
      layer.on('mouseover', function(e) {
        if (!self.isLayerHighlighted(layer)) {
          layer.setStyle({
            weight: 3,
            fillOpacity: 0.4
          });
        }
      });

      layer.on('mouseout', function(e) {
        if (!self.isLayerHighlighted(layer)) {
          layer.setStyle(self.defaultStyle);
        }
      });
    });

    // Add click handler to map to clear selection
    this.map.on('click', function(e) {
      self.clearHighlights();
      self.closePaginatedPopup();
    });

    // Add popup close handler to clear highlights when popup is closed via X button
    this.map.on('popupclose', function(e) {
      console.log('Popup closed, event:', e);

      // Use a small delay to check if popup is really being closed or just updated
      setTimeout(function() {
        // If this was the paginated popup being closed (and it's actually gone)
        if (e.popup === self.paginatedPopup && !self.map.hasLayer(e.popup)) {
          console.log('Paginated popup closed by user');

          // Clear highlights (geometries return to default)
          self.clearHighlights();

          // Clean up pagination state
          self.paginatedPopup = null;
          self.overlappingFeatures = [];
          self.currentPageIndex = 0;
        }
        // If it was a single feature popup (not paginated) and really closed
        else if (!self.paginatedPopup && !self.map.hasLayer(e.popup)) {
          console.log('Single popup closed');

          // Clear highlights for single feature popups
          self.clearHighlights();
        }
        // Otherwise, it's just a content update or old popup being replaced - don't clear
      }, 10);
    });
  }

  /**
   * Find all features that contain the clicked point
   * Uses Leaflet's map.layerPointToContainerPoint and layer bounds/geometry checks
   */
  findOverlappingFeatures(latlng) {
    const overlapping = [];
    const point = this.map.latLngToLayerPoint(latlng);
    const tolerance = 10; // pixels

    this.publicationsLayer.eachLayer((layer) => {
      // Check if this layer contains the point
      if (this.layerContainsPoint(layer, latlng, point, tolerance)) {
        // GeoJSON can have ID at feature level or properties level
        const pubId = layer.feature.id || layer.feature.properties.id;

        // Debug logging
        const geomType = layer.feature?.geometry?.geometries?.[0]?.type ||
                        layer.feature?.geometry?.type;
        console.log(`Found overlapping feature [${pubId}]: ${layer.feature.properties.title} (${geomType})`);

        overlapping.push({
          layer: layer,
          feature: layer.feature,
          publicationId: pubId
        });
      }
    });

    console.log(`Total overlapping features at click location: ${overlapping.length}`);
    return overlapping;
  }

  /**
   * Check if a layer's geometry contains a point
   * Works directly with the GeoJSON feature geometry, not Leaflet layer types
   * Based on geojson-js-utils: https://github.com/max-mapper/geojson-js-utils
   */
  layerContainsPoint(layer, latlng, point, tolerance) {
    try {
      if (!layer.feature || !layer.feature.geometry) {
        return false;
      }

      const geometry = layer.feature.geometry;

      // Handle GeometryCollection (our format wraps everything in this)
      let actualGeometry = geometry;
      if (geometry.type === 'GeometryCollection' && geometry.geometries && geometry.geometries.length > 0) {
        actualGeometry = geometry.geometries[0];
      }

      const geomType = actualGeometry.type;
      const coords = actualGeometry.coordinates;

      // Point geometry
      if (geomType === 'Point') {
        return this.pointIntersectsPoint(latlng, coords, point, tolerance);
      }

      // LineString geometry
      if (geomType === 'LineString') {
        return this.pointIntersectsLineString(latlng, coords);
      }

      // Polygon geometry
      if (geomType === 'Polygon') {
        return this.pointInPolygonGeoJSON(latlng, coords);
      }

      // MultiPolygon geometry
      if (geomType === 'MultiPolygon') {
        for (let i = 0; i < coords.length; i++) {
          if (this.pointInPolygonGeoJSON(latlng, coords[i])) {
            return true;
          }
        }
        return false;
      }

      // MultiLineString geometry
      if (geomType === 'MultiLineString') {
        for (let i = 0; i < coords.length; i++) {
          if (this.pointIntersectsLineString(latlng, coords[i])) {
            return true;
          }
        }
        return false;
      }

      return false;
    } catch (e) {
      console.warn('Error checking layer containment:', e, layer);
      return false;
    }
  }

  /**
   * Check if a point intersects another point (for Point geometries)
   * GeoJSON Point coordinates are [lng, lat]
   */
  pointIntersectsPoint(latlng, pointCoords, clickPoint, tolerance) {
    // Create a marker at the point location
    const pointLng = pointCoords[0];
    const pointLat = pointCoords[1];
    const pointLatLng = L.latLng(pointLat, pointLng);
    const pointPixel = this.map.latLngToLayerPoint(pointLatLng);

    // Calculate pixel distance
    const dx = clickPoint.x - pointPixel.x;
    const dy = clickPoint.y - pointPixel.y;
    const distance = Math.sqrt(dx * dx + dy * dy);

    return distance <= tolerance;
  }

  /**
   * Check if a point intersects a LineString
   * GeoJSON LineString coordinates are [[lng, lat], [lng, lat], ...]
   */
  pointIntersectsLineString(latlng, lineCoords) {
    const threshold = 100; // meters

    for (let i = 0; i < lineCoords.length - 1; i++) {
      const start = L.latLng(lineCoords[i][1], lineCoords[i][0]);
      const end = L.latLng(lineCoords[i + 1][1], lineCoords[i + 1][0]);
      const distance = this.distanceToSegment(latlng, start, end);

      if (distance < threshold) {
        return true;
      }
    }

    return false;
  }

  /**
   * Point-in-polygon test for GeoJSON polygon coordinates
   * GeoJSON Polygon coordinates are [[[lng, lat], ...]] (array of rings)
   * First ring is exterior, subsequent rings are holes
   */
  pointInPolygonGeoJSON(latlng, polygonCoords) {
    // Check exterior ring
    if (polygonCoords.length === 0) {
      return false;
    }

    const exteriorRing = polygonCoords[0];
    if (!this.pointInRing(latlng, exteriorRing)) {
      return false;
    }

    // Check holes (if point is in a hole, it's not in the polygon)
    for (let i = 1; i < polygonCoords.length; i++) {
      if (this.pointInRing(latlng, polygonCoords[i])) {
        return false; // Point is in a hole
      }
    }

    return true;
  }

  /**
   * Point-in-ring test using ray casting algorithm
   * Ring coordinates are [[lng, lat], [lng, lat], ...]
   */
  pointInRing(latlng, ring) {
    const x = latlng.lng;
    const y = latlng.lat;
    let inside = false;

    for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
      const xi = ring[i][0]; // longitude
      const yi = ring[i][1]; // latitude
      const xj = ring[j][0];
      const yj = ring[j][1];

      const intersect = ((yi > y) !== (yj > y)) &&
                       (x < (xj - xi) * (y - yi) / (yj - yi) + xi);

      if (intersect) {
        inside = !inside;
      }
    }

    return inside;
  }


  /**
   * Calculate distance from point to line segment
   */
  distanceToSegment(point, segmentStart, segmentEnd) {
    const x = point.lng, y = point.lat;
    const x1 = segmentStart.lng, y1 = segmentStart.lat;
    const x2 = segmentEnd.lng, y2 = segmentEnd.lat;

    const A = x - x1;
    const B = y - y1;
    const C = x2 - x1;
    const D = y2 - y1;

    const dot = A * C + B * D;
    const lenSq = C * C + D * D;
    let param = -1;

    if (lenSq !== 0) {
      param = dot / lenSq;
    }

    let xx, yy;

    if (param < 0) {
      xx = x1;
      yy = y1;
    } else if (param > 1) {
      xx = x2;
      yy = y2;
    } else {
      xx = x1 + param * C;
      yy = y1 + param * D;
    }

    const dx = x - xx;
    const dy = y - yy;

    // Return approximate distance in meters
    return Math.sqrt(dx * dx + dy * dy) * 111000; // Rough conversion
  }

  /**
   * Show paginated popup for overlapping features
   */
  showPaginatedPopup(overlapping, latlng) {
    console.log('showPaginatedPopup called with latlng:', latlng);

    // Close existing popup FIRST (before setting new location)
    this.closePaginatedPopup();

    // Now set new state
    this.overlappingFeatures = overlapping;
    this.currentPageIndex = 0;
    this.currentClickLocation = latlng;

    console.log('Set currentClickLocation to:', this.currentClickLocation);

    // Show first page
    this.updatePaginatedPopup();
  }

  /**
   * Update the paginated popup content
   */
  updatePaginatedPopup() {
    if (this.overlappingFeatures.length === 0) return;

    const currentFeature = this.overlappingFeatures[this.currentPageIndex];
    const properties = currentFeature.feature.properties;
    const featureId = currentFeature.feature.id || properties.id;

    // Select and highlight the current publication
    this.selectPublication(currentFeature);

    // Build popup content using the standard popup format
    let html = '<div class="paginated-publication-popup">';

    // Pagination header
    html += '<div style="background: #f8f9fa; padding: 8px 10px; margin: -10px -10px 10px -10px; border-radius: 3px 3px 0 0; border-bottom: 2px solid #158F9B;">';
    html += '<div style="display: flex; justify-content: space-between; align-items: center;">';
    html += `<span style="font-size: 12px; color: #666;"><i class="fas fa-layer-group"></i> ${this.currentPageIndex + 1} of ${this.overlappingFeatures.length} works</span>`;
    html += '<div class="pagination-controls" style="display: flex; gap: 5px;">';

    // Previous button
    if (this.currentPageIndex > 0) {
      html += '<button class="page-btn page-prev" style="background: #158F9B; color: white; border: none; padding: 4px 8px; border-radius: 3px; cursor: pointer; font-size: 12px;" title="Previous publication"><i class="fas fa-chevron-left"></i></button>';
    } else {
      html += '<button style="background: #ccc; color: #666; border: none; padding: 4px 8px; border-radius: 3px; cursor: not-allowed; font-size: 12px;" disabled><i class="fas fa-chevron-left"></i></button>';
    }

    // Next button
    if (this.currentPageIndex < this.overlappingFeatures.length - 1) {
      html += '<button class="page-btn page-next" style="background: #158F9B; color: white; border: none; padding: 4px 8px; border-radius: 3px; cursor: pointer; font-size: 12px;" title="Next publication"><i class="fas fa-chevron-right"></i></button>';
    } else {
      html += '<button style="background: #ccc; color: #666; border: none; padding: 4px 8px; border-radius: 3px; cursor: not-allowed; font-size: 12px;" disabled><i class="fas fa-chevron-right"></i></button>';
    }

    html += '</div></div></div>';

    // Publication content (using standard popup format)
    html += '<div class="publication-content" style="max-height: 350px; overflow-y: auto;">';

    // Title with link to work landing page
    if (properties.title) {
      html += `<h3 style="margin: 0 0 10px 0; font-size: 16px;">${properties.title}</h3>`;

      if (properties.doi) {
        html += `<div style="margin-bottom: 10px;"><a href="/work/${encodeURIComponent(properties.doi)}/" class="btn btn-sm btn-primary" style="color: white; text-decoration: none; padding: 5px 10px; border-radius: 3px; display: inline-block; background: #158F9B; border: none;">View work details</a></div>`;
      } else if (featureId) {
        html += `<div style="margin-bottom: 10px;"><a href="/work/${featureId}/" class="btn btn-sm btn-primary" style="color: white; text-decoration: none; padding: 5px 10px; border-radius: 3px; display: inline-block; background: #158F9B; border: none;">View work details</a></div>`;
      }
    }

    // Source details
    if (properties.source_details) {
      const s = properties.source_details;
      const name = s.display_name || s.name || 'Unknown';
      html += `<div style="margin-bottom: 5px;"><strong>Source:</strong> ${name}</div>`;

      if (s.abbreviated_title) {
        html += `<div style="margin-bottom: 5px;"><em>${s.abbreviated_title}</em></div>`;
      }

      if (s.homepage_url) {
        html += `<div style="margin-bottom: 5px;"><a href="${s.homepage_url}" target="_blank"><i class="fas fa-external-link-alt"></i> Visit journal site</a></div>`;
      }

      if (s.issn_l) {
        html += `<div style="margin-bottom: 5px;"><strong>ISSN-L:</strong> <a href="https://openalex.org/sources/issn:${s.issn_l}" target="_blank"><i class="fas fa-external-link-alt"></i> ${s.issn_l}</a></div>`;
      }

      if (s.publisher_name && s.publisher_name !== name) {
        html += `<div style="margin-bottom: 5px;"><strong>Publisher:</strong> ${s.publisher_name}</div>`;
      }

      if ('is_oa' in s) {
        const status = s.is_oa ? 'Open Access' : 'Closed Access';
        html += `<div style="margin-bottom: 5px;"><strong>Access:</strong> ${status}</div>`;
      }

      if (s.cited_by_count != null) {
        html += `<div style="margin-bottom: 5px;">Cited by ${s.cited_by_count} works</div>`;
      }

      if (s.works_count != null) {
        html += `<div style="margin-bottom: 5px;">${s.works_count} works hosted</div>`;
      }
    }

    // Time period
    if (properties.timeperiod_startdate && properties.timeperiod_enddate) {
      html += `<div style="margin-bottom: 5px;"><strong>Timeperiod:</strong> from ${properties.timeperiod_startdate} to ${properties.timeperiod_enddate}</div>`;
    }

    // Abstract
    if (properties.abstract) {
      html += `<div style="margin-top: 10px;"><p style="margin: 0;">${properties.abstract}</p></div>`;
    }

    // Work source link
    if (properties.url) {
      html += `<div style="margin-top: 8px;"><a href="${properties.url}" target="_blank"><i class="fas fa-external-link-alt"></i> Visit work</a></div>`;
    }

    // OpenAlex link
    if (properties.openalex_id) {
      html += `<div style="margin-top: 8px;"><a href="${properties.openalex_id}" target="_blank" style="color: #2563eb;"><i class="fas fa-external-link-alt"></i> View in OpenAlex</a></div>`;
    }

    html += '</div></div>';

    // Create or update popup
    if (!this.paginatedPopup) {
      this.paginatedPopup = L.popup({
        maxWidth: 400,
        minWidth: 300,
        maxHeight: 500,
        closeButton: true,
        autoClose: false,
        closeOnClick: false,
        className: 'paginated-popup'
      })
      .setLatLng(this.currentClickLocation)
      .setContent(html)
      .openOn(this.map);
    } else {
      this.paginatedPopup.setContent(html);
    }

    // Add event listeners for pagination buttons
    setTimeout(() => {
      const prevBtn = document.querySelector('.page-prev');
      const nextBtn = document.querySelector('.page-next');

      if (prevBtn) {
        prevBtn.addEventListener('click', (e) => {
          e.stopPropagation();
          this.goToPreviousPage();
        });
      }

      if (nextBtn) {
        nextBtn.addEventListener('click', (e) => {
          e.stopPropagation();
          this.goToNextPage();
        });
      }
    }, 50);
  }

  /**
   * Go to previous page in pagination
   */
  goToPreviousPage() {
    if (this.currentPageIndex > 0) {
      this.currentPageIndex--;
      this.updatePaginatedPopup();
    }
  }

  /**
   * Go to next page in pagination
   */
  goToNextPage() {
    if (this.currentPageIndex < this.overlappingFeatures.length - 1) {
      this.currentPageIndex++;
      this.updatePaginatedPopup();
    }
  }

  /**
   * Show publication popup for single feature
   */
  showPublicationPopup(featureData, latlng) {
    // Use layer's built-in popup if it exists
    if (featureData.layer && featureData.layer.getPopup()) {
      featureData.layer.openPopup();
    }
  }

  /**
   * Close the paginated popup and clear highlights
   */
  closePaginatedPopup() {
    if (this.paginatedPopup) {
      this.map.closePopup(this.paginatedPopup);
      this.paginatedPopup = null;
    }

    // Clear highlights when closing popup
    this.clearHighlights();

    // Clear pagination state
    this.overlappingFeatures = [];
    this.currentPageIndex = 0;
    // Don't clear currentClickLocation here - it's set in showPaginatedPopup
  }

  /**
   * Select a publication and highlight all its geometries
   */
  selectPublication(featureData) {
    const publicationId = featureData.publicationId;

    // Clear previous highlights
    this.clearHighlights();

    // Find all layers belonging to this publication
    const publicationLayers = [];
    this.publicationsLayer.eachLayer((layer) => {
      if (layer.feature) {
        const layerPubId = layer.feature.id || layer.feature.properties.id;
        if (layerPubId === publicationId) {
          publicationLayers.push(layer);
        }
      }
    });

    // Check if we're in pagination mode (based on overlapping features, not popup existence)
    const inPaginationMode = this.overlappingFeatures.length > 0;

    // Highlight all layers for this publication
    publicationLayers.forEach((layer, index) => {
      const isCircleMarker = layer instanceof L.CircleMarker;

      if (layer === featureData.layer) {
        // The clicked layer gets selected style
        if (isCircleMarker) {
          // For CircleMarkers (point geometries), use modified style
          layer.setStyle({
            color: this.selectedStyle.color,
            fillColor: this.selectedStyle.fillColor || this.selectedStyle.color,
            weight: this.selectedStyle.weight,
            fillOpacity: this.selectedStyle.fillOpacity,
            radius: 10  // Increase radius for visibility
          });
        } else {
          // For polygons/lines, use full selected style
          layer.setStyle(this.selectedStyle);
        }
        layer.bringToFront();

        // Only open individual popup if NOT in pagination mode
        if (!inPaginationMode && layer.getPopup()) {
          layer.openPopup();
        }
      } else {
        // Other geometries of the same publication get highlight style
        if (isCircleMarker) {
          // For CircleMarkers, use modified highlight style
          layer.setStyle({
            color: this.highlightStyle.color,
            fillColor: this.highlightStyle.fillColor || this.highlightStyle.color,
            weight: this.highlightStyle.weight,
            fillOpacity: this.highlightStyle.fillOpacity,
            radius: 8  // Slightly increased radius
          });
        } else {
          // For polygons/lines, use full highlight style
          layer.setStyle(this.highlightStyle);
        }
        layer.bringToFront();
      }

      this.highlightedLayers.push(layer);
    });

    this.selectedPublication = publicationId;

    // Show info about multiple geometries
    if (publicationLayers.length > 1) {
      this.showGeometryInfo(publicationLayers.length);
    }
  }

  /**
   * Show information about multiple geometries
   */
  showGeometryInfo(count) {
    // Remove existing info if any
    const existing = document.getElementById('geometry-info');
    if (existing) {
      existing.remove();
    }

    // Create info display
    const info = document.createElement('div');
    info.id = 'geometry-info';
    info.style.cssText = `
      position: fixed;
      bottom: 30px;
      left: 50%;
      transform: translateX(-50%);
      background: rgba(247, 147, 30, 0.95);
      color: white;
      padding: 10px 15px;
      border-radius: 5px;
      box-shadow: 0 2px 8px rgba(0,0,0,0.3);
      z-index: 1000;
      font-size: 14px;
      pointer-events: none;
      animation: fadeIn 0.3s;
    `;
    info.innerHTML = `<i class="fas fa-draw-polygon"></i> This publication has ${count} geometries (all highlighted)`;

    document.body.appendChild(info);

    // Remove after 4 seconds
    setTimeout(() => {
      if (info.parentNode) {
        info.style.animation = 'fadeOut 0.3s';
        setTimeout(() => info.remove(), 300);
      }
    }, 4000);
  }

  /**
   * Clear all highlights and reset to default style
   */
  clearHighlights() {
    this.highlightedLayers.forEach((layer) => {
      const isCircleMarker = layer instanceof L.CircleMarker;

      if (isCircleMarker) {
        // For CircleMarkers, reset to default marker style with default radius
        layer.setStyle({
          ...this.defaultStyle,
          fillColor: null,
          radius: 6  // Default radius for CircleMarkers
        });
      } else {
        // For polygons/lines, reset to default style
        layer.setStyle({
          ...this.defaultStyle,
          dashArray: null,    // Remove dashed border (from selectedStyle)
          fillColor: null     // Remove explicit fill color (from selected/highlightStyle)
        });
      }
    });

    this.highlightedLayers = [];
    this.selectedPublication = null;

    // Remove info display
    const info = document.getElementById('geometry-info');
    if (info) {
      info.remove();
    }
  }

  /**
   * Check if a layer is currently highlighted
   */
  isLayerHighlighted(layer) {
    return this.highlightedLayers.includes(layer);
  }
}

// Add CSS animations
const style = document.createElement('style');
style.textContent = `
  @keyframes fadeIn {
    from { opacity: 0; transform: translateY(-10px); }
    to { opacity: 1; transform: translateY(0); }
  }

  @keyframes fadeOut {
    from { opacity: 1; }
    to { opacity: 0; }
  }

  .overlap-selection .overlap-item:active {
    transform: scale(0.98);
  }
`;
document.head.appendChild(style);
