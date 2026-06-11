# SPDX-FileCopyrightText: 2026 OPTIMETA and KOMET projects <https://projects.tib.eu/komet>
# SPDX-License-Identifier: GPL-3.0-or-later

"""HTTP client + cache wrapper for the EO4GEO BoK snapshot.

Upstream API contract (verified 2026-05-08):
    GET {BOK_API_BASE}/{version}/concepts.json
        -> object keyed by concept code, each value:
           { id, name, uri, description, contributors[], references[],
             relations[{name, source, target}], skills[] }

We persist a *trimmed* per-concept payload (id, name, uri, description,
parent_code, breadcrumb) — enough to render chips, autosuggest, and
JSON-LD. The full upstream response is ~2 MiB; the trim is ~250 KiB.

Caching: Django's `default` alias (DB-backed, durable). Lazy on miss —
populated on the first request after deploy or after the
`refresh_bok_snapshot` management command runs.
"""

from __future__ import annotations

import logging
from typing import Any

import requests
from django.conf import settings
from django.core.cache import cache
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)


BOK_HTTP_TIMEOUT = 30
BOK_CACHE_KEY_TEMPLATE = "bok:concepts:{version}:v1"
# No TTL — cache lives until refresh_bok_snapshot rerun or cache.clear().
BOK_CACHE_TIMEOUT = None


def _version() -> str:
    return getattr(settings, "BOK_VERSION", "v9")


def _api_base() -> str:
    return getattr(settings, "BOK_API_BASE", "https://eo4geo-bok.firebaseio.com").rstrip("/")


def _cache_key(version: str | None = None) -> str:
    return BOK_CACHE_KEY_TEMPLATE.format(version=version or _version())


# Module-level alias so callers/tests can mention the active key directly.
BOK_CACHE_KEY = _cache_key()


def _bok_session() -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=3,
        connect=3,
        read=3,
        backoff_factor=1.5,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset(["GET"]),
        respect_retry_after_header=True,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    session.headers.update({
        "User-Agent": settings.OPTIMAP_USER_AGENT,
        "Accept": "application/json",
    })
    return session


def _trim_concept(code: str, raw: dict[str, Any]) -> dict[str, Any]:
    """Reduce a raw upstream concept to the fields we need."""
    description = raw.get("description") or ""
    if isinstance(description, str) and len(description) > 600:
        description = description[:600].rstrip() + "…"
    concept_base = getattr(settings, "BOK_CONCEPT_BASE_URL", "https://geospacebok.eu").rstrip("/")
    return {
        "code": code,
        "id": raw.get("id") or code,
        "name": raw.get("name") or code,
        "uri": f"{concept_base}/{code}",
        "description": description,
    }


def _derive_parents(raw_concepts: dict[str, dict]) -> dict[str, str]:
    """Walk every concept's relations to build {child_code: parent_code}.

    `relations` lives on whichever endpoint the relation describes; for
    "is subconcept of" the *source* is the child and the *target* is the
    parent. A concept can appear in multiple subconcept relations from
    different children — we only care about the *parent of <code>*, so we
    look for relations on `<code>` itself where `source == code`.
    """
    parents: dict[str, str] = {}
    for code, raw in raw_concepts.items():
        for rel in raw.get("relations") or []:
            if rel.get("name") == "is subconcept of" and rel.get("source") == code:
                parents[code] = rel.get("target")
                break
    return parents


def _build_breadcrumb(code: str, parents: dict[str, str], names: dict[str, str]) -> list[dict[str, str]]:
    """[{code, name}, …] from the topmost ancestor down to (but not
    including) `code` itself. Empty for top-level concepts."""
    chain: list[str] = []
    seen: set[str] = set()
    parent = parents.get(code)
    while parent and parent not in seen:
        chain.append(parent)
        seen.add(parent)
        parent = parents.get(parent)
    return [{"code": c, "name": names.get(c, c)} for c in reversed(chain)]


def fetch_bok_snapshot(version: str | None = None) -> dict[str, dict[str, Any]]:
    """Fetch the live snapshot from upstream. No cache touch.

    Returns the trimmed dict (also writes nothing).
    """
    version = version or _version()
    url = f"{_api_base()}/{version}/concepts.json"
    logger.info("Fetching EO4GEO BoK snapshot: %s", url)
    session = _bok_session()
    resp = session.get(url, timeout=BOK_HTTP_TIMEOUT)
    resp.raise_for_status()
    raw = resp.json()
    if not isinstance(raw, dict):
        raise ValueError(f"BoK snapshot at {url} is not a JSON object (got {type(raw).__name__})")

    parents = _derive_parents(raw)
    names = {code: (raw[code].get("name") or code) for code in raw}

    snapshot: dict[str, dict[str, Any]] = {}
    for code, item in raw.items():
        if not isinstance(item, dict):
            continue
        trimmed = _trim_concept(code, item)
        trimmed["parent_code"] = parents.get(code) or ""
        trimmed["breadcrumb"] = _build_breadcrumb(code, parents, names)
        snapshot[code] = trimmed

    logger.info("Trimmed BoK snapshot: %d concepts (version=%s)", len(snapshot), version)
    return snapshot


def get_concepts(version: str | None = None) -> dict[str, dict[str, Any]]:
    """Return the cached trimmed snapshot, fetching on miss."""
    version = version or _version()
    key = _cache_key(version)
    cached = cache.get(key)
    if cached is not None:
        return cached
    snapshot = fetch_bok_snapshot(version)
    cache.set(key, snapshot, timeout=BOK_CACHE_TIMEOUT)
    return snapshot


def get_concept(code: str, version: str | None = None) -> dict[str, Any] | None:
    if not code:
        return None
    return get_concepts(version).get(code)


def is_known(code: str, version: str | None = None) -> bool:
    return code in get_concepts(version)


def resolve(codes: list[str], version: str | None = None) -> list[dict[str, Any]]:
    """Resolve a list of stored codes to render-ready dicts.

    Returns one entry per input code, preserving order. Unknown codes get
    a stub entry with `orphan=True` so the UI can render a greyed chip.
    """
    snapshot = get_concepts(version)
    out: list[dict[str, Any]] = []
    for code in codes or []:
        concept = snapshot.get(code)
        if concept is None:
            out.append({
                "code": code,
                "name": code,
                "uri": "",
                "description": "",
                "parent_code": "",
                "breadcrumb": [],
                "orphan": True,
            })
        else:
            out.append({**concept, "orphan": False})
    return out


def invalidate_cache(version: str | None = None) -> None:
    cache.delete(_cache_key(version))


# --- search -----------------------------------------------------------------

# Minimum query length before the autosuggest endpoint returns matches.
# The UI also enforces this client-side; the server enforces it as a
# defense against hot-keystroke flooding.
MIN_QUERY_LENGTH = 3


def _tokenize(text: str) -> list[str]:
    return [t for t in text.replace("/", " ").replace("-", " ").split() if t]


def search(query: str, limit: int = 10, version: str | None = None) -> list[dict[str, Any]]:
    """Ranked autosuggest over the cached snapshot.

    Tiers (lower score = better):
        0 exact code match (case-insensitive)
        1 exact name match
        2 name starts with query
        3 any token in name starts with query
        4 query is a substring of name
        5 query is a substring of description
    Ties broken by code (lexicographic).
    """
    if not query or len(query.strip()) < MIN_QUERY_LENGTH:
        return []
    q = query.strip().lower()
    snapshot = get_concepts(version)

    scored: list[tuple[int, str, dict[str, Any]]] = []
    for code, concept in snapshot.items():
        name = (concept.get("name") or "").lower()
        description = (concept.get("description") or "").lower()
        code_lc = code.lower()

        if code_lc == q:
            tier = 0
        elif name == q:
            tier = 1
        elif name.startswith(q):
            tier = 2
        elif any(tok.startswith(q) for tok in _tokenize(name)):
            tier = 3
        elif q in name:
            tier = 4
        elif q in description:
            tier = 5
        else:
            continue
        scored.append((tier, code, concept))

    scored.sort(key=lambda x: (x[0], x[1]))
    limit = max(1, min(limit, 50))
    return [c for _, _, c in scored[:limit]]


def match_text_to_codes(names: list[str], version: str | None = None) -> list[str]:
    """Resolve a list of human-readable concept names to known BoK codes.

    Only exact name matches (case-insensitive) are accepted — fuzzy matches
    are dropped. Returns de-duplicated codes in input order, skipping blanks
    and names that don't resolve to any known concept.
    """
    seen: set[str] = set()
    out: list[str] = []
    for name in names:
        name = name.strip()
        if not name:
            continue
        hits = search(name, limit=1, version=version)
        if hits and hits[0]["name"].lower() == name.lower():
            code = hits[0]["code"]
            if code not in seen:
                seen.add(code)
                out.append(code)
    return out
