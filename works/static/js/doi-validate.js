// SPDX-FileCopyrightText: 2026 OPTIMETA and KOMET projects <https://projects.tib.eu/komet>
// SPDX-License-Identifier: GPL-3.0-or-later

// Lightweight client-side DOI validation/normalization, mirroring the
// server-side works.utils.identifiers.normalize_doi helper. No dependencies.
// The server always re-validates; this only drives the form's enabled state.
(function (global) {
  "use strict";

  // Crossref's recommended DOI pattern, applied after stripping any resolver prefix.
  var DOI_RE = /^10\.\d{4,9}\/\S+$/i;

  var PREFIXES = [
    "https://dx.doi.org/",
    "http://dx.doi.org/",
    "https://doi.org/",
    "http://doi.org/",
    "dx.doi.org/",
    "doi.org/",
    "doi:",
  ];

  // Return the bare DOI for a DOI or DOI URL, or null if it is not a valid DOI.
  function normalizeDoi(raw) {
    if (!raw) {
      return null;
    }
    var doi = String(raw).trim();
    if (!doi) {
      return null;
    }
    var lowered = doi.toLowerCase();
    for (var i = 0; i < PREFIXES.length; i++) {
      if (lowered.indexOf(PREFIXES[i]) === 0) {
        doi = doi.slice(PREFIXES[i].length);
        break;
      }
    }
    doi = doi.trim();
    return DOI_RE.test(doi) ? doi : null;
  }

  function isValidDoi(raw) {
    return normalizeDoi(raw) !== null;
  }

  global.OPTIMAP_DOI = { normalizeDoi: normalizeDoi, isValidDoi: isValidDoi };
})(window);
