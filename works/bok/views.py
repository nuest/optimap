# SPDX-FileCopyrightText: 2026 OPTIMETA and KOMET projects <https://projects.tib.eu/komet>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Public API endpoints for the EO4GEO Body of Knowledge."""

import logging

import requests
from django.http import JsonResponse
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import (
    OpenApiParameter,
    OpenApiResponse,
    extend_schema,
    inline_serializer,
)
from rest_framework import serializers as drf_serializers
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny

from works.bok import client as bok_client

logger = logging.getLogger(__name__)


_BOK_ERROR = inline_serializer(
    name="BokErrorResponse",
    fields={"error": drf_serializers.CharField()},
)


@extend_schema(
    summary="Autosuggest EO4GEO BoK concepts",
    description=(
        "Searches the cached EO4GEO Body of Knowledge snapshot and returns "
        "ranked matches for use in autosuggest inputs. The query must be at "
        "least 3 characters; shorter queries return an empty list. Concepts "
        "are matched against code, name (token-prefix and substring) and "
        "description, in that priority order. Results include a parent "
        "breadcrumb so the UI can disambiguate similarly-named concepts."
    ),
    tags=["Body of Knowledge"],
    parameters=[
        OpenApiParameter(
            "q", str, OpenApiParameter.QUERY, required=True,
            description="Free-text query (≥ 3 characters).",
        ),
        OpenApiParameter(
            "limit", int, OpenApiParameter.QUERY, required=False,
            description="Maximum number of results (default 10, max 50).",
        ),
    ],
    responses={
        (200, "application/json"): OpenApiTypes.OBJECT,
        502: OpenApiResponse(_BOK_ERROR, description="Upstream BoK API unreachable."),
    },
)
@api_view(["GET"])
@permission_classes([AllowAny])
def bok_search(request):
    query = (request.GET.get("q") or "").strip()
    try:
        limit = int(request.GET.get("limit", "10"))
    except (TypeError, ValueError):
        limit = 10

    try:
        results = bok_client.search(query, limit=limit)
    except requests.RequestException as exc:
        logger.warning("BoK upstream unreachable: %s", exc)
        return JsonResponse(
            {"error": "EO4GEO BoK service is currently unreachable."},
            status=502,
        )

    return JsonResponse({
        "query": query,
        "min_query_length": bok_client.MIN_QUERY_LENGTH,
        "count": len(results),
        "results": results,
    })
