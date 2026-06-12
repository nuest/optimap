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

// HTML templates used with L.Util.template({key} substitution).
// Only use for values we control (URLs, counts, dates, enum strings).
// User-supplied free text (title, abstract, names) stays in template literals
// to avoid conflicts with {…} patterns that may appear in scientific text.
const _TMPL = {
  statusBadge:
    '<span style="display:inline-block;padding:2px 7px;border-radius:3px;font-size:11px;font-weight:600;{style}">{label}</span>',
  workLink:
    '<div style="margin-bottom:10px;"><a href="/work/{path}/" class="btn btn-sm btn-primary" style="color:white;text-decoration:none;padding:5px 10px;border-radius:3px;display:inline-block;">View work details</a></div>',
  sourceSite:
    '<div><a href="{url}" target="_blank"><i class="fas fa-external-link-alt"></i> Visit source website</a></div>',
  sourceIssn:
    '<div><strong>ISSN-L:</strong> <a href="https://openalex.org/sources/issn:{issn}" target="_blank"><i class="fas fa-external-link-alt"></i> {issn}</a></div>',
  sourceAccess:  '<div><strong>Access:</strong> {access}</div>',
  sourceCited:   '<div>Cited by {count} works</div>',
  sourceWorks:   '<div>{count} works hosted</div>',
  timeperiod:    '<div><strong>Timeperiod:</strong> from {start} to {end}</div>',
  workUrl:
    '<div><a href="{url}" target="_blank"><i class="fas fa-external-link-alt"></i> Visit work</a></div>',
  openalexUrl:
    '<div style="margin-top:8px;"><a href="{url}" target="_blank" style="color:#2563eb;"><i class="fas fa-external-link-alt"></i> View in OpenAlex</a></div>',
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
  let html = L.Util.template(_TMPL.statusBadge, { style, label });
  if (status !== 'p') {
    html += ' <small style="color:#888;">— not visible to anonymous users</small>';
  }
  return html;
}

// ---------------------------------------------------------------------------
// Shared lazy-load cache and fetcher — used by both the single-feature popup
// below and the paginated popup in map-interaction.js.
// ---------------------------------------------------------------------------

/** @type {Object.<string|number, Object>} */
window.workDetailsCache = {};

/**
 * Fetch full work details from the API and cache them.
 * Returns the cached value if already fetched.
 * @param {string|number} featureId
 * @returns {Promise<Object>} Resolved properties object.
 */
window.fetchWorkDetails = async function(featureId) {
  if (window.workDetailsCache[featureId]) return window.workDetailsCache[featureId];
  const resp = await fetch(`/api/v1/works/${featureId}/?format=json`);
  const data = await resp.json();
  // GeoFeatureModelSerializer places non-geometry fields under `properties`.
  window.workDetailsCache[featureId] = data.properties ?? data;
  return window.workDetailsCache[featureId];
};

/**
 * Render the rich detail section of a popup (source, abstract, dates, links).
 * Exported on window so map-interaction.js can reuse it for the paginated popup.
 * @param {Object} p - Work properties object (from the full serializer).
 * @param {string|number} featureId
 * @returns {string} HTML string.
 */
window.renderPublicationContent = function(p, featureId) {
  let html = '';

  // Source details
  if (p.source_details) {
    const s = p.source_details;
    const name = s.display_name || s.name || 'Unknown';
    html += `<div><strong>Source:</strong> ${name}</div>`;
    if (s.abbreviated_title) {
      html += `<div><em>${s.abbreviated_title}</em></div>`;
    }
    if (s.homepage_url) {
      html += L.Util.template(_TMPL.sourceSite, { url: s.homepage_url });
    }
    if (s.issn_l) {
      html += L.Util.template(_TMPL.sourceIssn, { issn: s.issn_l });
    }
    if (s.publisher_name && s.publisher_name !== name) {
      html += `<div><strong>Publisher:</strong> ${s.publisher_name}</div>`;
    }
    if ('is_oa' in s) {
      html += L.Util.template(_TMPL.sourceAccess, { access: s.is_oa ? 'Open Access' : 'Closed Access' });
    }
    if (s.cited_by_count != null) {
      html += L.Util.template(_TMPL.sourceCited, { count: s.cited_by_count });
    }
    if (s.works_count != null) {
      html += L.Util.template(_TMPL.sourceWorks, { count: s.works_count });
    }
  }

  if (p.timeperiod_startdate && p.timeperiod_enddate) {
    html += L.Util.template(_TMPL.timeperiod, { start: p.timeperiod_startdate, end: p.timeperiod_enddate });
  }

  if (p.abstract) {
    html += `<div><p>${p.abstract}</p></div>`;
  }

  if (p.url) {
    html += L.Util.template(_TMPL.workUrl, { url: p.url });
  }

  if (p.openalex_id) {
    html += L.Util.template(_TMPL.openalexUrl, { url: p.openalex_id });
  }

  return html;
};

// ---------------------------------------------------------------------------
// Internal renderers
// ---------------------------------------------------------------------------

function _renderHeader(p, featureId) {
  let html = '';
  // Status badge — only present for admin/curator; anonymous users see published only.
  if (p.status) {
    html += `<div style="margin-bottom:8px;">${publicationStatusBadgeHTML(p.status, p.status_display)}</div>`;
  }
  if (p.title) {
    html += `<h3>${p.title}</h3>`;
  }
  // "View work details" button
  const doi = p.doi;
  if (doi) {
    html += L.Util.template(_TMPL.workLink, { path: encodeURIComponent(doi) });
  } else if (featureId) {
    html += L.Util.template(_TMPL.workLink, { path: featureId });
  }
  return html;
}

function _renderMinimalPopup(p, featureId) {
  return '<div>' + _renderHeader(p, featureId) +
    '<p style="color:#666;font-size:12px;margin-top:6px;">Loading details…</p></div>';
}

function _renderFullPopup(p, featureId) {
  return '<div>' + _renderHeader(p, featureId) +
    (window.renderPublicationContent(p, featureId) || '') + '</div>';
}

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

/**
 * Generate popup content for a publication feature.
 * With chunked loading the initial feature only has minimal properties
 * (id, title, doi, status). Full details are fetched lazily on first open.
 * @param {Object} feature - GeoJSON feature object
 * @param {Object} layer - Leaflet layer object
 */
function publicationPopup(feature, layer) {
  const p = feature.properties;
  // GeoJSON convention puts the primary key at feature.id rather than properties.
  const featureId = feature.id || p.id;
  const container = document.createElement('div');

  function paint(props) {
    container.innerHTML = props
      ? _renderFullPopup(props, featureId)
      : _renderMinimalPopup(p, featureId);
  }

  // If already cached (e.g. popup reopened), render immediately.
  paint(window.workDetailsCache[featureId] ?? null);
  layer.bindPopup(container, { maxWidth: 300, maxHeight: 250 });

  layer.on('popupopen', async () => {
    if (window.workDetailsCache[featureId]) {
      paint(window.workDetailsCache[featureId]);
      layer.getPopup().update();
      return;
    }
    try {
      await window.fetchWorkDetails(featureId);
    } catch (_) {
      // Leave "Loading details…" — don't crash.
    }
    if (window.workDetailsCache[featureId]) {
      paint(window.workDetailsCache[featureId]);
      layer.getPopup().update();
    }
  });
}
