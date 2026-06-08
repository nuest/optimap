// SPDX-FileCopyrightText: 2022 OPTIMETA and KOMET projects <https://projects.tib.eu/komet>
// SPDX-License-Identifier: GPL-3.0-or-later

// publications/static/js/map-popup.js
// Shared popup content generator for publication features on Leaflet maps

// Inline-style colours that mirror Bootstrap badge variants used in the templates.
const _STATUS_BADGE_STYLE = {
  p: 'background:#28a745;color:#fff',          // Published  — green
  h: 'background:#17a2b8;color:#fff',          // Harvested  — teal
  c: 'background:#007bff;color:#fff',          // Contributed — blue
  d: 'background:#6c757d;color:#fff',          // Draft      — grey
  t: 'background:#ffc107;color:#212529',       // Testing    — yellow (dark text)
  w: 'background:#dc3545;color:#fff',          // Withdrawn  — red
};

/**
 * Return a small inline-styled status badge (and a "not public" note for
 * unpublished statuses).  Returns '' when status is absent, so calling code
 * needs no guard of its own.
 * @param {string} status - Work.status code ('p','h','c','d','t','w')
 * @param {string} statusDisplay - Human-readable label (e.g. "Harvested")
 */
function publicationStatusBadgeHTML(status, statusDisplay) {
  if (!status) return '';
  const style = _STATUS_BADGE_STYLE[status] || 'background:#6c757d;color:#fff';
  const label = statusDisplay || status;
  let html = `<span style="display:inline-block;padding:2px 7px;border-radius:3px;font-size:11px;font-weight:600;${style}">${label}</span>`;
  if (status !== 'p') {
    html += ' <small style="color:#888;">— not visible to anonymous users</small>';
  }
  return html;
}

/**
 * Generate popup content for a publication feature
 * @param {Object} feature - GeoJSON feature object
 * @param {Object} layer - Leaflet layer object
 */
function publicationPopup(feature, layer) {
  const p = feature.properties;
  // GeoJSON convention (and rest_framework_gis ``GeoFeatureModelSerializer``)
  // puts the primary key at ``feature.id`` rather than in ``feature.properties``,
  // so we have to merge both before deciding what landing-page URL to build —
  // otherwise works without a DOI render no "View work details" button at all.
  const featureId = feature.id || p.id;
  let html = '<div>';

  // Status badge — only present in the GeoJSON when the viewer is an admin/curator
  // (anonymous users only see published works, so the badge would always say
  // "Published" and adds no value for them).
  if (p.status) {
    html += `<div style="margin-bottom:8px;">${publicationStatusBadgeHTML(p.status, p.status_display)}</div>`;
  }

  if (p.title) {
    html += `<h3>${p.title}</h3>`;
  }

  // "View work details" button — render whenever we have an identifier, even
  // when the title is absent, so the user can still navigate to the landing
  // page from a single-feature popup.
  if (p.doi) {
    html += `<div style="margin-bottom: 10px;"><a href="/work/${encodeURIComponent(p.doi)}/" class="btn btn-sm btn-primary" style="color: white; text-decoration: none; padding: 5px 10px; border-radius: 3px; display: inline-block;">View work details</a></div>`;
  } else if (featureId) {
    html += `<div style="margin-bottom: 10px;"><a href="/work/${featureId}/" class="btn btn-sm btn-primary" style="color: white; text-decoration: none; padding: 5px 10px; border-radius: 3px; display: inline-block;">View work details</a></div>`;
  }

  // Source details from nested object
  if (p.source_details) {
    const s = p.source_details;

    // Display name
    const name = s.display_name || s.name || 'Unknown';
    html += `<div><strong>Source:</strong> ${name}</div>`;

    // Abbreviated title
    if (s.abbreviated_title) {
      html += `<div><em>${s.abbreviated_title}</em></div>`;
    }

    // Homepage link
    if (s.homepage_url) {
      html += `<div><a href="${s.homepage_url}" target="_blank"><i class="fas fa-external-link-alt"></i> Visit source website</a></div>`;
    }

    // ISSN-L link
    if (s.issn_l) {
      html +=
        `<div><strong>ISSN-L:</strong> ` +
        `<a href="https://openalex.org/sources/issn:${s.issn_l}" target="_blank"><i class="fas fa-external-link-alt"></i> ${s.issn_l}</a></div>`;
    }

    // Publisher (only if different from display name)
    if (s.publisher_name && s.publisher_name !== name) {
      html += `<div><strong>Publisher:</strong> ${s.publisher_name}</div>`;
    }

    // Open access status
    if ('is_oa' in s) {
      const status = s.is_oa ? 'Open Access' : 'Closed Access';
      html += `<div><strong>Access:</strong> ${status}</div>`;
    }

    // Citation count
    if (s.cited_by_count != null) {
      html += `<div>Cited by ${s.cited_by_count} works</div>`;
    }

    // Works count
    if (s.works_count != null) {
      html += `<div>${s.works_count} works hosted</div>`;
    }
  }

  // Time period
  if (p.timeperiod_startdate && p.timeperiod_enddate) {
    html +=
      `<div><strong>Timeperiod:</strong> from ${p.timeperiod_startdate} to ${p.timeperiod_enddate}</div>`;
  }

  // Abstract
  if (p.abstract) html += `<div><p>${p.abstract}</p></div>`;

  // Work source link
  if (p.url) {
    html += `<div><a href="${p.url}" target="_blank"><i class="fas fa-external-link-alt"></i> Visit work</a></div>`;
  }

  // OpenAlex link
  if (p.openalex_id) {
    html += `<div style="margin-top: 8px;"><a href="${p.openalex_id}" target="_blank" style="color: #2563eb;"><i class="fas fa-external-link-alt"></i> View in OpenAlex</a></div>`;
  }

  html += '</div>';
  layer.bindPopup(html, { maxWidth: 300, maxHeight: 250 });
}

/**
 * Style function for publication features
 * Uses teal color scheme from feed pages
 * @param {Object} feature - GeoJSON feature object
 * @returns {Object} Style object for Leaflet
 */
function publicationStyle(feature) {
  return {
    color: '#158F9B',
    weight: 2,
    fillOpacity: 0.3,
  };
}
