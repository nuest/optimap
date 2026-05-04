# SPDX-FileCopyrightText: 2026 OPTIMETA and KOMET projects <https://projects.tib.eu/komet>
# SPDX-License-Identifier: GPL-3.0-or-later

"""SEO helpers for OPTIMAP — issue #22.

Builds ``django-meta`` ``Meta`` objects and Google Scholar ``citation_*``
lists for work landing pages, the homepage, and feed pages. Templates emit
Open Graph + Twitter Card + schema.org JSON-LD via ``django-meta``; the
Scholar tags are rendered inline because django-meta does not model them.
"""

from __future__ import annotations

import json
import re
from typing import Iterable
from urllib.parse import quote, urljoin

from django.conf import settings
from django.urls import reverse
from meta.views import Meta


_WS = re.compile(r"\s+")


def _abs(request, path: str) -> str:
    """Build an absolute URL — prefers the request host so previews and
    canonical URLs work in dev (``127.0.0.1:8002``) without overriding
    settings."""
    if request is not None:
        return request.build_absolute_uri(path)
    return urljoin(getattr(settings, "BASE_URL", "http://localhost:8000/"), path)


def _truncate_for_description(text: str | None, n: int = 200) -> str:
    if not text:
        return ""
    cleaned = _WS.sub(" ", text).strip()
    if len(cleaned) <= n:
        return cleaned
    # Cut on a word boundary.
    cut = cleaned[: n - 1].rsplit(" ", 1)[0]
    return cut + "…"


def _normalize_author_list(work) -> list[str]:
    """Return ``[\"Given Family\", …]`` from a Work's ArrayField, mirroring
    the human-readable form used on the landing page."""
    raw = work.authors or []
    out: list[str] = []
    for a in raw:
        name = (a or "").strip()
        if "," in name and not name.endswith(","):
            family, given = (s.strip() for s in name.split(",", 1))
            name = f"{given} {family}".strip()
        if name:
            out.append(name)
    return out


def build_work_meta(request, work) -> Meta:
    """``Meta`` for a work landing page. Includes Open Graph, Twitter Card,
    and schema.org ``ScholarlyArticle`` JSON-LD. Image is omitted when the
    work has no geometry (per Q3)."""
    title = work.title or "Untitled work"
    description = _truncate_for_description(work.abstract, n=200)
    canonical = _abs(request, reverse("optimap:work-landing", args=[work.get_identifier()]))

    has_geom = bool(work.geometry and not work.geometry.empty)
    image = None
    if has_geom:
        image = _abs(
            request,
            reverse("optimap:work-preview", args=[work.get_identifier()]),
        )

    keywords: list[str] = []
    if work.keywords:
        keywords.extend(k for k in work.keywords if k)
    if work.topics:
        keywords.extend(t for t in work.topics if t)

    authors = _normalize_author_list(work)

    schema = _build_schema_org(work, request, canonical, image, authors, keywords, description)

    meta = Meta(
        request=request,
        title=title,
        description=description,
        keywords=keywords or None,
        url=canonical,
        image=image,
        object_type="article",
        site_name="OPTIMAP",
        twitter_creator=None,
        twitter_site="@OPTIMAP",
        schemaorg_title=title,
        schemaorg_description=description,
        custom_namespace="article",
    )
    # Map preview is 1200x630 — set the OG hints so previews render at full size.
    if image:
        meta.image_width = 1200
        meta.image_height = 630
    # Article-typed Open Graph extras.
    extra: list[tuple[str, str, str]] = [
        ("property", "og:type", "article"),
    ]
    if work.publicationDate:
        extra.append(("property", "article:published_time", work.publicationDate.isoformat()))
    for author in authors:
        extra.append(("property", "article:author", author))
    if work.source and getattr(work.source, "name", None):
        extra.append(("property", "article:section", str(work.source.name)))
    meta.extra_props = {tag: val for _, tag, val in extra}  # property=… name=… handled below
    meta.extra_custom_props = extra
    meta.schema = schema
    return meta


def _build_schema_org(work, request, canonical, image, authors, keywords, description) -> dict:
    """Schema.org ``ScholarlyArticle`` JSON-LD. Mirrors what we *consume* from
    Janeway in ``works/tasks.py`` — closing the loop: we now publish the same
    metadata vocabulary that we read."""
    payload: dict = {
        "@context": "https://schema.org",
        "@type": "ScholarlyArticle",
        "name": work.title,
        "headline": work.title,
        "url": canonical,
    }
    if description:
        payload["description"] = description
    if work.doi:
        payload["identifier"] = f"doi:{work.doi}"
    same_as: list[str] = []
    if work.doi:
        same_as.append(f"https://doi.org/{work.doi}")
    if work.openalex_id:
        oa = work.openalex_id
        same_as.append(oa if oa.startswith("http") else f"https://openalex.org/{oa}")
    if same_as:
        payload["sameAs"] = same_as if len(same_as) > 1 else same_as[0]
    if work.publicationDate:
        payload["datePublished"] = work.publicationDate.isoformat()
    if authors:
        payload["author"] = [{"@type": "Person", "name": a} for a in authors]
    if keywords:
        payload["keywords"] = list(keywords)
    if image:
        payload["image"] = image
    if work.source and getattr(work.source, "name", None):
        publisher: dict = {
            "@type": "Organization",
            "name": str(work.source.name),
        }
        if getattr(work.source, "homepage_url", None):
            publisher["url"] = work.source.homepage_url
        payload["publisher"] = publisher

        periodical: dict = {"@type": "Periodical", "name": str(work.source.name)}
        if getattr(work.source, "issn_l", None):
            periodical["issn"] = work.source.issn_l

        # Nest PublicationVolume / PublicationIssue when we have them so
        # consumers see the full citation structure; fall back to the flat
        # Periodical shape when neither is set.
        is_part_of = periodical
        if work.volume:
            is_part_of = {
                "@type": "PublicationVolume",
                "volumeNumber": work.volume,
                "isPartOf": periodical,
            }
        if work.issue:
            is_part_of = {
                "@type": "PublicationIssue",
                "issueNumber": work.issue,
                "isPartOf": is_part_of,
            }
        payload["isPartOf"] = is_part_of
    if work.first_page:
        payload["pageStart"] = work.first_page
    if work.last_page:
        payload["pageEnd"] = work.last_page
    if work.geometry and not work.geometry.empty:
        payload["spatialCoverage"] = {
            "@type": "Place",
            "geo": json.loads(work.geometry.geojson),
        }
    temporal = _format_temporal_iso(work)
    if temporal:
        payload["temporalCoverage"] = temporal
    payload["inLanguage"] = "en"
    return payload


def _format_temporal_iso(work) -> str | None:
    """Format the work's ArrayField temporal extent as an ISO 8601 interval —
    ``start/end``, ``start/..``, or ``../end``. Returns ``None`` when both
    sides are empty."""
    s_list = work.timeperiod_startdate or []
    e_list = work.timeperiod_enddate or []
    s = (s_list[0] if s_list else None) or None
    e = (e_list[0] if e_list else None) or None
    if not s and not e:
        return None
    return f"{s or '..'}/{e or '..'}"


def _derive_pdf_url(work) -> str | None:
    """Return ``work.url`` when it confidently points at a PDF, else None.

    Emitting a non-PDF URL as ``citation_pdf_url`` causes Zotero to attach
    an HTML snapshot as if it were a PDF, so we err strict. (Note:
    ``Work.openalex_fulltext_origin`` is a *type* string from OpenAlex —
    e.g. "journal", "repository" — not a URL, so it can't be used here.)
    """
    if work.url and work.url.lower().endswith(".pdf"):
        return work.url
    return None


def citation_meta_tags(work, request) -> list[dict]:
    """List of Google Scholar ``citation_*`` tag dicts ``{name, content}``.
    The template renders these directly because django-meta has no model
    for Scholar tags. Repeating ``citation_author`` and ``citation_keywords``
    is intentional — Scholar expects one tag per item.
    """
    tags: list[dict] = []
    if work.title:
        tags.append({"name": "citation_title", "content": work.title})
    for author in _normalize_author_list(work):
        tags.append({"name": "citation_author", "content": author})
    if work.publicationDate:
        tags.append({
            "name": "citation_publication_date",
            "content": work.publicationDate.isoformat(),
        })
    if work.doi:
        tags.append({"name": "citation_doi", "content": work.doi})
    canonical = _abs(request, reverse("optimap:work-landing", args=[work.get_identifier()]))
    tags.append({"name": "citation_abstract_html_url", "content": canonical})
    if work.abstract:
        tags.append({"name": "citation_abstract", "content": work.abstract})
    if work.source and getattr(work.source, "name", None):
        tags.append({"name": "citation_journal_title", "content": str(work.source.name)})
        tags.append({"name": "citation_publisher", "content": str(work.source.name)})
    if work.source and getattr(work.source, "issn_l", None):
        tags.append({"name": "citation_issn", "content": work.source.issn_l})
    if work.volume:
        tags.append({"name": "citation_volume", "content": work.volume})
    if work.issue:
        tags.append({"name": "citation_issue", "content": work.issue})
    if work.first_page:
        tags.append({"name": "citation_firstpage", "content": work.first_page})
    if work.last_page:
        tags.append({"name": "citation_lastpage", "content": work.last_page})
    keywords: list[str] = []
    if work.keywords:
        keywords.extend(k for k in work.keywords if k)
    if work.topics:
        keywords.extend(t for t in work.topics if t)
    for kw in keywords:
        tags.append({"name": "citation_keywords", "content": kw})
    tags.append({"name": "citation_language", "content": "en"})
    pdf_url = _derive_pdf_url(work)
    if pdf_url:
        tags.append({"name": "citation_pdf_url", "content": pdf_url})
    return tags


def coins_title(work) -> str | None:
    """Return the value for a COinS ``<span class="Z3988" title="…">`` for
    this work, or ``None`` when the work has no title.

    COinS encodes one OpenURL kev/mtx context object as a single URL-encoded
    query string. Zotero (and other reference managers) read it as a
    fallback when the richer Embedded Metadata translator finds nothing —
    or to enable multi-item save on list pages.
    """
    if not work.title:
        return None

    pairs: list[tuple[str, str]] = [
        ("ctx_ver", "Z39.88-2004"),
        ("rft_val_fmt", "info:ofi/fmt:kev:mtx:journal"),
        ("rft.genre", "article"),
        ("rft.atitle", work.title),
    ]
    for author in _normalize_author_list(work):
        pairs.append(("rft.au", author))
    if work.publicationDate:
        pairs.append(("rft.date", work.publicationDate.isoformat()))
    if work.source and getattr(work.source, "name", None):
        pairs.append(("rft.jtitle", str(work.source.name)))
    if work.source and getattr(work.source, "issn_l", None):
        pairs.append(("rft.issn", work.source.issn_l))
    if work.volume:
        pairs.append(("rft.volume", work.volume))
    if work.issue:
        pairs.append(("rft.issue", work.issue))
    if work.first_page:
        pairs.append(("rft.spage", work.first_page))
    if work.last_page:
        pairs.append(("rft.epage", work.last_page))
    if work.doi:
        pairs.append(("rft_id", f"info:doi/{work.doi}"))

    return "&".join(f"{k}={quote(v, safe='')}" for k, v in pairs)


def build_homepage_meta(request) -> Meta:
    """``WebSite`` + ``SearchAction`` schema.org for the homepage."""
    canonical = _abs(request, reverse("optimap:main"))
    description = (
        "OPTIMAP is a geospatial discovery portal for research articles "
        "based on open metadata. Browse publications by region, time, and "
        "subject."
    )
    meta = Meta(
        request=request,
        title="OPTIMAP — geospatial discovery of research articles",
        description=description,
        keywords=["OPTIMAP", "geospatial search", "open access", "research articles", "KOMET"],
        url=canonical,
        site_name="OPTIMAP",
        object_type="website",
        schemaorg_title="OPTIMAP",
        schemaorg_description=description,
    )
    meta.schema = {
        "@context": "https://schema.org",
        "@type": "WebSite",
        "name": "OPTIMAP",
        "url": canonical,
        "description": description,
        "potentialAction": {
            "@type": "SearchAction",
            "target": {
                "@type": "EntryPoint",
                "urlTemplate": _abs(request, "/?q={search_term_string}"),
            },
            "query-input": "required name=search_term_string",
        },
    }
    return meta


def build_feed_page_meta(request, *, region_name: str | None,
                         region_bbox: Iterable[float] | None,
                         page_url: str) -> Meta:
    """``CollectionPage`` schema.org for region/feed landing pages."""
    canonical = _abs(request, page_url)
    title = (
        f"{region_name} — OPTIMAP regional feed"
        if region_name
        else "OPTIMAP feeds"
    )
    description = (
        f"Recent research articles with geographic coverage in {region_name}."
        if region_name
        else "OPTIMAP regional and global feeds."
    )
    meta = Meta(
        request=request,
        title=title,
        description=description,
        url=canonical,
        site_name="OPTIMAP",
        object_type="website",
        schemaorg_title=title,
        schemaorg_description=description,
    )
    schema: dict = {
        "@context": "https://schema.org",
        "@type": "CollectionPage",
        "name": title,
        "url": canonical,
        "description": description,
    }
    if region_name and region_bbox:
        west, south, east, north = region_bbox
        schema["about"] = {
            "@type": "Place",
            "name": region_name,
            "geo": {
                "@type": "GeoShape",
                "box": f"{south} {west} {north} {east}",
            },
        }
    elif region_name:
        schema["about"] = {"@type": "Place", "name": region_name}
    meta.schema = schema
    return meta
