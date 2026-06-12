# SPDX-FileCopyrightText: 2025 OPTIMETA and KOMET projects <https://projects.tib.eu/komet>
# SPDX-License-Identifier: GPL-3.0-or-later

import json


def publications_to_geojson(publications) -> str:
    """Serialize a list (or queryset) of Work objects to a GeoJSON FeatureCollection string."""
    features = []

    for work in publications:
        if not work.geometry or work.geometry.empty:
            continue

        source_details = None
        if work.source:
            source_details = {
                "name": work.source.name,
                "display_name": work.source.name,
                "abbreviated_title": work.source.abbreviated_title,
                "homepage_url": work.source.homepage_url,
                "issn_l": work.source.issn_l,
                "publisher_name": work.source.publisher_name,
                "is_oa": work.source.is_oa,
                "is_preprint": work.source.is_preprint,
                "cited_by_count": work.source.cited_by_count,
                "works_count": work.source.works_count,
            }

        features.append(
            {
                "type": "Feature",
                "geometry": json.loads(work.geometry.geojson),
                "properties": {
                    "id": work.id,
                    "title": work.title,
                    "doi": work.doi,
                    "url": work.url,
                    "abstract": work.abstract,
                    "source": work.source.name if work.source else None,
                    "source_details": source_details,
                    "status": work.status,
                    "status_display": work.get_status_display(),
                    "publicationDate": work.publicationDate.isoformat() if work.publicationDate else None,
                    "timeperiod_startdate": work.timeperiod_startdate,
                    "timeperiod_enddate": work.timeperiod_enddate,
                    "authors": work.authors,
                    "keywords": work.keywords,
                    "topics": work.topics,
                    "openalex_id": work.openalex_id,
                    "openalex_match_info": work.openalex_match_info,
                    "openalex_fulltext_origin": work.openalex_fulltext_origin,
                    "openalex_is_retracted": work.openalex_is_retracted,
                    "openalex_ids": work.openalex_ids,
                    "openalex_open_access_status": work.openalex_open_access_status,
                },
            }
        )

    return json.dumps({"type": "FeatureCollection", "features": features})
