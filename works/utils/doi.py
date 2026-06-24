# SPDX-FileCopyrightText: 2026 OPTIMETA and KOMET projects <https://projects.tib.eu/komet>
# SPDX-License-Identifier: GPL-3.0-or-later

"""DOI helpers shared by the harvester and the dedup layer.

The only logic here today is *version* normalization for preprint servers that
mint one DOI per version of a preprint (ESS Open Archive / Authorea). Collapsing
those versions onto a single canonical Work keeps OPTIMAP's count aligned with
the upstream "unique preprints" figure instead of inflating it by every ``/v2``.
"""

import re

#: Current ESS Open Archive / Authorea era: ``10.22541/essoar.<a>.<b>/vN``.
#: The version is the trailing ``/vN`` path segment.
_VERSION_RE_SLASH = re.compile(r"^(?P<base>.*/essoar\.[^/]+)/v(?P<version>\d+)$", re.IGNORECASE)

#: Legacy ESSOAr era: ``10.1002/essoar.<id>.<N>``. The work id carries no dots,
#: so the trailing ``.N`` segment is the version. Anchored to the ``10.1002``
#: prefix on purpose: the current era's versionless base is ``essoar.<a>.<b>``
#: (two dotted numbers), which this pattern would otherwise misread as base
#: ``essoar.<a>`` + version ``<b>``.
_VERSION_RE_DOTTED = re.compile(r"^(?P<base>10\.1002/essoar\.\d+)\.(?P<version>\d+)$", re.IGNORECASE)


def normalize_versioned_doi(doi):
    """Return ``(versionless_base, version)`` for a versioned preprint DOI.

    Handles the two ESSOAr/Authorea version encodings:

    * current ``.../essoar.<a>.<b>/vN`` → strip the ``/vN`` segment;
    * legacy ``10.../essoar.<id>.<N>`` → strip the trailing ``.N`` segment.

    ``version`` is the integer version number. Any DOI that is not a recognized
    versioned ESSOAr DOI (including ``None``) is returned unchanged with
    ``version=None`` — this must never touch plain DOIs from other sources.
    """
    if not doi:
        return doi, None
    candidate = doi.strip()
    for pattern in (_VERSION_RE_SLASH, _VERSION_RE_DOTTED):
        match = pattern.match(candidate)
        if match:
            return match.group("base"), int(match.group("version"))
    return doi, None
