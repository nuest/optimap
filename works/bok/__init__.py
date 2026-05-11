# SPDX-FileCopyrightText: 2026 OPTIMETA and KOMET projects <https://projects.tib.eu/komet>
# SPDX-License-Identifier: GPL-3.0-or-later

"""EO4GEO Body of Knowledge integration.

Thin client + cached snapshot of the public EO4GEO BoK
(https://eo4geo-uji.web.app/documentation/API.pdf) used to drive concept
tagging on works. The snapshot is fetched once from
`https://eo4geo-bok.firebaseio.com/<version>/concepts.json` and stored in
the Django `default` cache (DB-backed, durable across restarts).
"""

from works.bok.client import (
    fetch_bok_snapshot,
    get_concepts,
    get_concept,
    is_known,
    resolve,
    search,
    invalidate_cache,
    BOK_CACHE_KEY,
)
from works.bok.eligibility import (
    enabled_collection_identifiers,
    is_collection_filter_active,
    is_work_eligible,
)

__all__ = [
    "fetch_bok_snapshot",
    "get_concepts",
    "get_concept",
    "is_known",
    "resolve",
    "search",
    "invalidate_cache",
    "BOK_CACHE_KEY",
    "enabled_collection_identifiers",
    "is_collection_filter_active",
    "is_work_eligible",
]
