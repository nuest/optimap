# SPDX-FileCopyrightText: 2022 OPTIMETA and KOMET projects <https://projects.tib.eu/komet>
# SPDX-License-Identifier: GPL-3.0-or-later

"""publications API views."""

import json
import logging
import os
import shutil
import tempfile
import uuid
import zipfile
from pathlib import Path

from rest_framework import viewsets, status
from rest_framework_gis import filters
from rest_framework.permissions import IsAuthenticatedOrReadOnly, AllowAny
from rest_framework.decorators import action
from rest_framework.response import Response
from drf_spectacular.utils import (
    extend_schema, extend_schema_view, inline_serializer, OpenApiResponse, OpenApiExample,
)
from drf_spectacular.types import OpenApiTypes
from rest_framework import serializers as drf_serializers
from django.conf import settings
from django.contrib.gis.geos import Polygon, Point, MultiPoint

# Import geoextent at module level
import geoextent.lib.extent as geoextent

from .models import Work, Source, Subscription, GlobalRegion
from .utils.provenance import public_subset
from .serializers import (
    WorkSerializer,
    SourceSerializer,
    SubscriptionSerializer,
    GlobalRegionSerializer,
    GeoextentExtractSerializer,
    GeoextentRemoteSerializer,
    GeoextentRemoteGetSerializer,
    GeoextentBatchSerializer,
)

logger = logging.getLogger(__name__)


# Reusable error-response schema. Most error paths in this module return
# `{"error": "<message>"}` (and sometimes also `{"details": "<…>"}`); a
# couple of validation paths fall back to DRF's serializer-error envelope.
# Schema-wise both fit `additionalProperties: true`, so a single shape covers them.
_ERROR_RESPONSE = inline_serializer(
    name="ErrorResponse",
    fields={
        "error": drf_serializers.CharField(),
        "details": drf_serializers.CharField(required=False),
    },
)


@extend_schema_view(
    list=extend_schema(summary="List harvested data sources", tags=["Sources"]),
    retrieve=extend_schema(
        summary="Retrieve a source by ID",
        tags=["Sources"],
        responses={
            200: SourceSerializer,
            404: OpenApiResponse(_ERROR_RESPONSE, description="No source with this ID."),
        },
    ),
)
class SourceViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Source.objects.all()
    serializer_class = SourceSerializer
    permission_classes = [IsAuthenticatedOrReadOnly]


@extend_schema_view(
    list=extend_schema(
        summary="List published works (paginated GeoJSON)",
        description=(
            "Returns published works as a GeoJSON `FeatureCollection`. Admins additionally "
            "see drafts and harvested-but-unpublished works. Filter the spatial slice with "
            "`?in_bbox=west,south,east,north`."
        ),
        tags=["Works"],
    ),
    retrieve=extend_schema(
        summary="Retrieve a work by numeric ID",
        description="See the work landing page (`/work/<id>/`) for the human-readable view.",
        tags=["Works"],
        responses={
            200: WorkSerializer,
            404: OpenApiResponse(_ERROR_RESPONSE, description="No work with this ID, or the work is not yet published and the request is anonymous."),
        },
    ),
)
class WorkViewSet(viewsets.ReadOnlyModelViewSet):
    bbox_filter_field = "geometry"
    filter_backends = (filters.InBBoxFilter,)
    serializer_class = WorkSerializer
    permission_classes = [IsAuthenticatedOrReadOnly]

    def get_queryset(self):
        """
        Return all publications for admin users, only published ones for others.
        Sorted by creation date (newest first) to match the works list page.

        For the ``provenance`` action: curators can access works in their
        collections at any publication status (not just published ones), so
        they can view provenance for harvested/contributed/draft works too.
        """
        if self.request.user.is_authenticated and self.request.user.is_staff:
            return Work.objects.all().order_by("-creationDate", "-id").distinct()
        if getattr(self, 'action', None) == 'provenance' and self.request.user.is_authenticated:
            curated = Work.objects.filter(collections__curators=self.request.user)
            public  = Work.objects.filter(status="p")
            return (curated | public).distinct()
        return Work.objects.filter(status="p").order_by("-creationDate", "-id").distinct()

    @extend_schema(
        summary="Retrieve provenance for a work",
        tags=["Works"],
        description=(
            "Returns the structured provenance record for a work — where it was harvested from, "
            "per-field metadata attribution, OpenAlex enrichment result, reverse-geocoding details, "
            "and a chronological audit log of re-harvest/contribution/publish events.\n\n"
            "**Access tiers:**\n"
            "- **Staff** and **curators of any collection this work belongs to** receive the full "
            "provenance, including `harvest.original_record`, `openalex_match.top_candidate`, "
            "and `user_id` / `user_email` fields in events.\n"
            "- **All other callers** (including anonymous users) receive the public subset with "
            "those keys removed.\n\n"
            "**`harvest` keys:**\n"
            "| Key | Type | Description |\n"
            "|-----|------|-------------|\n"
            "| `harvester` | string | Task function name: `harvest_oai_endpoint`, `harvest_rss_endpoint`, `harvest_crossref_prefix`, `harvest_mountain_wetlands`, `harvest_openalex_source` |\n"
            "| `source_name` | string | Display name of the source |\n"
            "| `source_type` | string | One of: `oai-pmh`, `ojs`, `janeway`, `rss`, `crossref-prefix`, `mountain-wetlands`, `openalex` |\n"
            "| `source_url` | string | Harvest endpoint URL |\n"
            "| `harvested_at` | string | ISO 8601 timestamp of the harvest |\n"
            "| `harvesting_event_id` | integer | FK to the `HarvestingEvent` record |\n"
            "| `doi` | string | DOI as recorded at harvest time |\n"
            "| `original_record` | object | Raw upstream record (staff/curators only) |\n\n"
            "**`metadata_sources` keys and values:**\n"
            "Each key names a Work field; the value names where that field's data came from.\n"
            "| Key | Possible values |\n"
            "|-----|-----------------|\n"
            "| `authors` | `original_source`, `openalex`, `crossref` |\n"
            "| `keywords` | `original_source`, `openalex` |\n"
            "| `topics` | `openalex` |\n"
            "| `type` | `openalex` |\n"
            "| `geometry` | `DC.SpatialCoverage`, `DC.box`, `link rel=alternate geo+json`, `study_sites` |\n"
            "| `doi` | `original_source`, `openalex` |\n"
            "| `date` | `original_source (year-only)` |\n"
            "| `volume` / `issue` / `first_page` / `last_page` | `openalex` |\n"
            "| `biblio` | `crossref` (volume/issue/pages from Crossref in one batch) |\n"
            "| `openalex_metadata` | `openalex` (any OpenAlex enrichment was applied) |\n"
            "| `openalex` | `primary` (work was harvested directly from OpenAlex as the primary source) |\n\n"
            "**`openalex_match` keys:**\n"
            "| Key | Type | Description |\n"
            "|-----|------|-------------|\n"
            "| `status` | string | `verified`, `unverified`, `none`, or `skipped` (skipped means the primary source already supplied DOI + authors) |\n"
            "| `score` | number | Confidence score 0.0–1.0 (absent when status is `none` or `skipped`) |\n"
            "| `matched_id` | string | OpenAlex work URL, e.g. `https://openalex.org/W2741809807` |\n"
            "| `top_candidate` | object | Raw OpenAlex API response for the best candidate (staff/curators only; only present when status is `unverified`) |\n\n"
            "**`geocoding` keys:**\n"
            "| Key | Type | Description |\n"
            "|-----|------|-------------|\n"
            "| `gazetteer` | string | Always `nominatim` |\n"
            "| `placename` | string | Human-readable location hierarchy, e.g. `Sulawesi, Indonesia` |\n"
            "| `country_code` | string | ISO 3166-1 alpha-2, e.g. `ID` |\n"
            "| `n_geocoded` | integer | Number of geometry points successfully reverse-geocoded |\n"
            "| `geocoded_at` | string | ISO 8601 timestamp |\n"
            "| `matches` | array | Per-point Nominatim results (display name, OSM type/id/url, lat, lon) |\n\n"
            "**`events` — event types:**\n"
            "| `type` | Extra fields | Description |\n"
            "|--------|-------------|-------------|\n"
            "| `harvest_update` | `harvesting_event_id` | Recorded each time an existing work is re-harvested |\n"
            "| `doi_backfill` | `doi`, `harvesting_event_id` | DOI was added to a previously DOI-less work |\n"
            "| `contribution` | `kinds` (array: `spatial`, `temporal`, `bok`), `user_id`\\*, `user_email`\\* | User added spatial/temporal/BoK metadata |\n"
            "| `publish` | `status_from`, `status_to`, `user_id`\\*, `user_email`\\* | Work was published |\n"
            "| `unpublish` | `status_from`, `user_id`\\*, `user_email`\\* | Work was unpublished |\n\n"
            "\\* `user_id` and `user_email` are present for staff and curators only.\n\n"
            "**Other top-level keys:**\n"
            "| Key | Type | Description |\n"
            "|-----|------|-------------|\n"
            "| `publication_notified_at` | string | ISO 8601 timestamp of when the publication notification email was sent to the contributor (suppresses duplicate sends on republish) |"
        ),
        responses={
            200: inline_serializer(
                name="ProvenanceResponse",
                fields={
                    "harvest": drf_serializers.DictField(
                        required=False,
                        help_text=(
                            "How and when this work was harvested. "
                            "Keys: harvester, source_name, source_type, source_url, "
                            "harvested_at, harvesting_event_id, doi. "
                            "Staff/curators also see original_record (raw upstream payload)."
                        ),
                    ),
                    "metadata_sources": drf_serializers.DictField(
                        required=False,
                        help_text=(
                            "Per-field attribution map. Keys name Work fields; values name their source. "
                            "Known keys: authors, keywords, topics, type, geometry, doi, date, "
                            "volume, issue, first_page, last_page, biblio, openalex_metadata, openalex. "
                            "Known values: original_source, openalex, crossref, DC.SpatialCoverage, "
                            "DC.box, link rel=alternate geo+json, study_sites, "
                            "original_source (year-only), primary."
                        ),
                    ),
                    "openalex_match": drf_serializers.DictField(
                        required=False,
                        help_text=(
                            "OpenAlex enrichment result. "
                            "Keys: status (verified/unverified/none/skipped), score (0.0–1.0), matched_id. "
                            "Staff/curators also see top_candidate."
                        ),
                    ),
                    "geocoding": drf_serializers.DictField(
                        required=False,
                        help_text=(
                            "Reverse-geocoding via Nominatim. "
                            "Keys: gazetteer, placename, country_code, n_geocoded, geocoded_at, matches."
                        ),
                    ),
                    "events": drf_serializers.ListField(
                        child=drf_serializers.DictField(),
                        required=False,
                        help_text=(
                            "Chronological audit log. Each event has type (string) and at (ISO timestamp). "
                            "Event types: harvest_update, doi_backfill, contribution, publish, unpublish. "
                            "user_id and user_email are present for staff/curators only."
                        ),
                    ),
                    "publication_notified_at": drf_serializers.CharField(
                        required=False,
                        help_text="ISO 8601 timestamp of when the publication notification email was sent to the contributor.",
                    ),
                },
            ),
            404: OpenApiResponse(
                _ERROR_RESPONSE,
                description="No work with this ID, or not yet published and the caller is anonymous.",
            ),
        },
        examples=[
            OpenApiExample(
                name="OAI-PMH work with OpenAlex enrichment (public response)",
                summary="Typical response for anonymous/regular-user callers",
                description=(
                    "A work harvested from an OAI-PMH journal, enriched by OpenAlex, "
                    "with a user-contributed geometry. Private keys (original_record, "
                    "top_candidate, user_id, user_email) are absent."
                ),
                value={
                    "harvest": {
                        "harvester": "harvest_oai_endpoint",
                        "source_name": "Earth System Science Data",
                        "source_type": "oai-pmh",
                        "source_url": "https://essd.copernicus.org/oai/",
                        "harvested_at": "2026-04-30T12:00:00+00:00",
                        "harvesting_event_id": 42,
                        "doi": "10.5194/essd-16-1234-2024",
                    },
                    "metadata_sources": {
                        "authors": "openalex",
                        "keywords": "original_source",
                        "topics": "openalex",
                        "geometry": "DC.SpatialCoverage",
                        "volume": "openalex",
                        "issue": "openalex",
                    },
                    "openalex_match": {
                        "status": "verified",
                        "score": 0.97,
                        "matched_id": "https://openalex.org/W2741809807",
                    },
                    "geocoding": {
                        "gazetteer": "nominatim",
                        "placename": "Sulawesi, Indonesia",
                        "country_code": "ID",
                        "n_geocoded": 2,
                        "geocoded_at": "2026-04-30T12:00:05+00:00",
                    },
                    "events": [
                        {
                            "type": "harvest_update",
                            "at": "2026-05-15T08:00:00+00:00",
                            "harvesting_event_id": 51,
                        },
                        {
                            "type": "contribution",
                            "at": "2026-05-01T09:15:00+00:00",
                            "kinds": ["spatial"],
                        },
                        {
                            "type": "publish",
                            "at": "2026-05-02T14:30:00+00:00",
                            "status_from": "c",
                            "status_to": "p",
                        },
                    ],
                    "publication_notified_at": "2026-05-02T14:30:01+00:00",
                },
                response_only=True,
                status_codes=["200"],
            ),
            OpenApiExample(
                name="MaRESS work (full response, staff/curator)",
                summary="Full provenance returned to staff or curators — includes private keys",
                description=(
                    "A work harvested from the Mountain Wetlands Repository (MaRESS API). "
                    "The geometry comes from study-site coordinates in the API record. "
                    "Includes original_record and user_id which are stripped for public callers."
                ),
                value={
                    "harvest": {
                        "harvester": "harvest_mountain_wetlands",
                        "source_name": "Mountain Wetlands Repository",
                        "source_type": "mountain-wetlands",
                        "source_url": "https://andes.mountain-wetlands-repository.info/api/v1/items/",
                        "harvested_at": "2026-03-10T06:30:00+00:00",
                        "harvesting_event_id": 17,
                        "doi": "10.5281/zenodo.7654321",
                        "original_record": {
                            "id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
                            "title": "Wetland extent Himalayan foothills 1990–2020",
                            "date": "2023",
                            "authors": [{"name": "Smith, J."}, {"name": "Patel, R."}],
                        },
                    },
                    "metadata_sources": {
                        "authors": "original_source",
                        "geometry": "study_sites",
                        "date": "original_source (year-only)",
                        "doi": "original_source",
                        "topics": "openalex",
                    },
                    "openalex_match": {
                        "status": "verified",
                        "score": 0.91,
                        "matched_id": "https://openalex.org/W3128445612",
                    },
                    "geocoding": {
                        "gazetteer": "nominatim",
                        "placename": "Uttarakhand, India",
                        "country_code": "IN",
                        "n_geocoded": 5,
                        "geocoded_at": "2026-03-10T06:30:10+00:00",
                    },
                    "events": [
                        {
                            "type": "contribution",
                            "at": "2026-03-12T11:00:00+00:00",
                            "kinds": ["temporal"],
                            "user_id": 7,
                            "user_email": "curator@example.org",
                        },
                        {
                            "type": "publish",
                            "at": "2026-03-13T09:00:00+00:00",
                            "status_from": "c",
                            "status_to": "p",
                            "user_id": 1,
                            "user_email": "admin@optimap.science",
                        },
                    ],
                },
                response_only=True,
                status_codes=["200"],
            ),
        ],
    )
    @action(detail=True, url_path='provenance', methods=['get'], permission_classes=[AllowAny])
    def provenance(self, request, pk=None):
        work = self.get_object()
        is_privileged = request.user.is_authenticated and (
            request.user.is_staff
            or work.collections.filter(curators=request.user).exists()
        )
        data = work.provenance if is_privileged else public_subset(work.provenance or {})
        response = Response(data)
        if request.user.is_authenticated:
            response['Cache-Control'] = 'private, no-store'
        else:
            response['Cache-Control'] = 'public, max-age=3600'
        return response


_SUBSCRIPTION_AUTH_RESPONSES = {
    401: OpenApiResponse(_ERROR_RESPONSE, description="Authentication credentials were not provided."),
    403: OpenApiResponse(_ERROR_RESPONSE, description="Authenticated user is not allowed to access this subscription."),
}


@extend_schema_view(
    list=extend_schema(
        summary="List the current user's subscriptions",
        tags=["Subscriptions"],
        responses={200: SubscriptionSerializer(many=True), **_SUBSCRIPTION_AUTH_RESPONSES},
    ),
    create=extend_schema(
        summary="Create a new subscription",
        tags=["Subscriptions"],
        responses={
            201: SubscriptionSerializer,
            400: OpenApiResponse(_ERROR_RESPONSE, description="Invalid payload (validation error)."),
            **_SUBSCRIPTION_AUTH_RESPONSES,
        },
    ),
    retrieve=extend_schema(
        summary="Retrieve a subscription by ID",
        tags=["Subscriptions"],
        responses={
            200: SubscriptionSerializer,
            404: OpenApiResponse(_ERROR_RESPONSE, description="No subscription with this ID owned by the current user."),
            **_SUBSCRIPTION_AUTH_RESPONSES,
        },
    ),
    update=extend_schema(
        summary="Replace a subscription",
        tags=["Subscriptions"],
        responses={
            200: SubscriptionSerializer,
            400: OpenApiResponse(_ERROR_RESPONSE, description="Invalid payload (validation error)."),
            404: OpenApiResponse(_ERROR_RESPONSE, description="No subscription with this ID owned by the current user."),
            **_SUBSCRIPTION_AUTH_RESPONSES,
        },
    ),
    partial_update=extend_schema(
        summary="Patch a subscription",
        tags=["Subscriptions"],
        responses={
            200: SubscriptionSerializer,
            400: OpenApiResponse(_ERROR_RESPONSE, description="Invalid payload (validation error)."),
            404: OpenApiResponse(_ERROR_RESPONSE, description="No subscription with this ID owned by the current user."),
            **_SUBSCRIPTION_AUTH_RESPONSES,
        },
    ),
    destroy=extend_schema(
        summary="Delete a subscription",
        tags=["Subscriptions"],
        responses={
            204: OpenApiResponse(description="Subscription deleted."),
            404: OpenApiResponse(_ERROR_RESPONSE, description="No subscription with this ID owned by the current user."),
            **_SUBSCRIPTION_AUTH_RESPONSES,
        },
    ),
)
class SubscriptionViewSet(viewsets.ModelViewSet):
    """
    Subscription view set.
    Each user can list, create, update, or delete their own Subscriptions.
    """
    bbox_filter_field = "region"
    filter_backends = (filters.InBBoxFilter,)
    serializer_class = SubscriptionSerializer
    permission_classes = [IsAuthenticatedOrReadOnly]

    def get_queryset(self):
        user = self.request.user
        return Subscription.objects.filter(user=user)

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)


@extend_schema_view(
    list=extend_schema(
        summary="List global regions (continents + oceans)",
        description=(
            "Continent and ocean polygons used by region-filtered feeds and subscriptions. "
            "Region slugs in this response are the ones to use in `/api/v1/feeds/optimap-<slug>.rss`."
        ),
        tags=["Global regions"],
    ),
    retrieve=extend_schema(
        summary="Retrieve a global region by ID",
        tags=["Global regions"],
        responses={
            200: GlobalRegionSerializer,
            404: OpenApiResponse(_ERROR_RESPONSE, description="No global region with this ID."),
        },
    ),
)
class GlobalRegionViewSet(viewsets.ReadOnlyModelViewSet):
    """
    GlobalRegion view set for continent and ocean geometries.
    Returns GeoJSON FeatureCollection for use in map layers.
    Read-only - regions are loaded via management command.
    """
    queryset = GlobalRegion.objects.all().order_by('region_type', 'name')
    serializer_class = GlobalRegionSerializer
    permission_classes = [AllowAny]


@extend_schema(tags=["Geoextent"])
class GeoextentViewSet(viewsets.ViewSet):
    """
    ViewSet for extracting geospatial and temporal extents from files.

    Provides three endpoints:
    - extract: Extract from uploaded file
    - extract-remote: Extract from remote repository (Zenodo, PANGAEA, etc.)
    - extract-batch: Extract from multiple uploaded files

    Public API - no authentication required.
    """
    permission_classes = [AllowAny]
    # Each @action declares its own request= via @extend_schema; this default
    # silences drf-spectacular's "unable to guess serializer" warning on the
    # parent ViewSet class.
    serializer_class = GeoextentExtractSerializer

    def _cleanup_temp_file(self, filepath):
        """Delete temporary file safely."""
        try:
            if filepath and os.path.exists(filepath):
                os.remove(filepath)
                logger.debug(f"Cleaned up temp file: {filepath}")
        except Exception as e:
            logger.warning(f"Failed to cleanup temp file {filepath}: {e}")

    def _save_uploaded_file(self, uploaded_file):
        """Save uploaded file to temporary location."""
        temp_dir = Path(settings.GEOEXTENT_TEMP_DIR)
        temp_dir.mkdir(exist_ok=True, parents=True)

        # Generate unique filename
        file_ext = Path(uploaded_file.name).suffix
        temp_filename = f"{uuid.uuid4()}{file_ext}"
        temp_path = temp_dir / temp_filename

        # Save file
        with open(temp_path, 'wb+') as destination:
            for chunk in uploaded_file.chunks():
                destination.write(chunk)

        logger.info(f"Saved uploaded file to: {temp_path}")
        return str(temp_path)

    def _process_geoextent_result(self, result):
        """
        Process geoextent result and format for API response.
        Geoextent returns the extent information directly.
        """
        try:
            # Check if result is None or empty
            if result is None:
                logger.error("Geoextent returned None - no valid spatial data found")
                return None

            if not isinstance(result, dict):
                logger.error(f"Geoextent returned unexpected type: {type(result)}")
                return None

            response = {
                'success': True,
            }

            # Add spatial extent if present
            if 'bbox' in result:
                response['spatial_extent'] = result['bbox']

            # Add temporal extent if present
            if 'tbox' in result:
                response['temporal_extent'] = result['tbox']

            # Add placename if present (geoextent extracts this)
            if 'placename' in result and result['placename']:
                response['placename'] = result['placename']

            # Add external metadata if present (from CrossRef/DataCite)
            if 'external_metadata' in result and result['external_metadata']:
                response['external_metadata'] = result['external_metadata']

            # Add metadata
            response['metadata'] = {}
            if 'format' in result:
                response['metadata']['file_format'] = result['format']
            if 'crs' in result:
                response['metadata']['crs'] = result['crs']
            if 'file_size_bytes' in result:
                response['metadata']['file_size_bytes'] = result['file_size_bytes']

            return response
        except Exception as e:
            logger.error(f"Error processing geoextent result: {e}")
            raise

    def _build_geoextent_extraction_metadata(self, geoextent_result, identifiers=None):
        """
        Build geoextent_extraction metadata object matching CLI output format.

        Directly copies geoextent output structure to avoid confusion between API and CLI.
        """
        import geoextent

        metadata = {
            'version': geoextent.__version__,
            'inputs': identifiers if identifiers else [],
        }

        # Directly copy statistics from extraction_metadata if available
        if 'extraction_metadata' in geoextent_result:
            em = geoextent_result['extraction_metadata']
            stats = {}
            # Copy exactly as geoextent CLI returns them
            if 'total_resources' in em:
                stats['files_processed'] = em['total_resources']
            if 'successful_resources' in em:
                stats['files_with_extent'] = em['successful_resources']
            if 'total_size' in em:
                stats['total_size'] = em['total_size']
            if stats:
                metadata['statistics'] = stats

        # Directly copy format and CRS from geoextent result
        if 'format' in geoextent_result:
            metadata['format'] = geoextent_result['format']
        if 'crs' in geoextent_result:
            metadata['crs'] = geoextent_result['crs']

        # Determine extent type
        if geoextent_result.get('convex_hull'):
            metadata['extent_type'] = 'convex_hull'
        else:
            metadata['extent_type'] = 'bounding_box'

        return metadata

    def _format_response(self, geoextent_result, structured_result, response_format, identifiers=None):
        """
        Format the response based on the requested format.

        Args:
            geoextent_result: Raw result from geoextent (dict with bbox, tbox, etc.)
            structured_result: Processed structured result from _process_geoextent_result
            response_format: One of 'geojson', 'wkt', 'wkb'
            identifiers: List of input identifiers (for metadata)

        Returns:
            Formatted response based on response_format
        """
        if response_format == 'geojson':
            # Use geoextent's format_extent_output to create proper GeoJSON
            # This ensures we match CLI output exactly and don't need to manually
            # reconstruct GeoJSON from bbox
            import geoextent.lib.helpfunctions as hf

            # Build extraction metadata for geoextent's formatter
            extraction_metadata = self._build_geoextent_extraction_metadata(
                geoextent_result,
                identifiers=identifiers
            )

            # Use geoextent's official formatter to create GeoJSON FeatureCollection
            # This handles bbox, convex_hull, tbox, placename, external_metadata automatically
            formatted_output = hf.format_extent_output(
                geoextent_result,
                output_format='geojson',
                extraction_metadata=extraction_metadata
            )

            return formatted_output

        elif response_format in ['wkt', 'wkb']:
            # For WKT/WKB, we need to convert bbox to geometry
            if not structured_result.get('spatial_extent'):
                return {
                    'success': False,
                    'error': f'Cannot convert to {response_format}: no spatial extent available'
                }

            bbox = structured_result['spatial_extent']

            # Handle convex hull format (list of points)
            if isinstance(bbox, list) and len(bbox) > 0 and isinstance(bbox[0], list):
                # Convex hull: list of [lon, lat] points
                if len(bbox) == 1:
                    # Single point
                    geom = Point(bbox[0][0], bbox[0][1], srid=4326)
                else:
                    # Multiple points - create polygon from points
                    points = [(point[0], point[1]) for point in bbox]
                    # Close the polygon if not already closed
                    if points[0] != points[-1]:
                        points.append(points[0])
                    geom = Polygon(points, srid=4326)

            # Handle standard bbox format [min_lon, min_lat, max_lon, max_lat]
            elif isinstance(bbox, list) and len(bbox) == 4:
                geom = Polygon.from_bbox(bbox)
                geom.srid = 4326
            else:
                return {
                    'success': False,
                    'error': f'Cannot convert bbox format {bbox} to {response_format}'
                }

            # Build geoextent_extraction metadata
            geoextent_extraction = self._build_geoextent_extraction_metadata(
                geoextent_result,
                identifiers=identifiers
            )

            # Create result with geometry in requested format
            if response_format == 'wkt':
                result = {'wkt': geom.wkt}
            else:  # wkb
                result = {'wkb': geom.wkb.hex()}

            # Add common fields
            result['crs'] = 'EPSG:4326'
            result['geoextent_extraction'] = geoextent_extraction

            # Add tbox if present (using same property name as CLI)
            if structured_result.get('temporal_extent'):
                result['tbox'] = structured_result['temporal_extent']
            if structured_result.get('placename'):
                result['placename'] = structured_result['placename']
            if structured_result.get('external_metadata'):
                result['external_metadata'] = structured_result['external_metadata']

            return result

        # Default fallback
        return structured_result

    @extend_schema(
        summary="Extract spatial / temporal extent from an uploaded file",
        description=(
            "Wraps the [geoextent](https://nuest.github.io/geoextent/) Python library, "
            "which inspects supported geospatial / data file formats and returns a "
            "bounding box and (when present) a temporal extent."
        ),
        tags=["Geoextent"],
        request=GeoextentExtractSerializer,
        responses={
            200: OpenApiResponse(OpenApiTypes.OBJECT, description="GeoJSON / WKT / WKB extent + metadata (see `response_format`)."),
            400: OpenApiResponse(_ERROR_RESPONSE, description="Invalid request body, unreadable file, or no spatial data extracted."),
            413: OpenApiResponse(_ERROR_RESPONSE, description=f"File exceeds OPTIMAP_GEOEXTENT_MAX_FILE_SIZE_MB."),
            500: OpenApiResponse(_ERROR_RESPONSE, description="Processing error inside the geoextent library."),
        },
    )
    @action(detail=False, methods=['post'])
    def extract(self, request):
        """
        Extract geospatial and temporal extent from uploaded file.

        POST /api/v1/geoextent/extract/
        """
        serializer = GeoextentExtractSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        uploaded_file = serializer.validated_data['file']
        bbox = serializer.validated_data['bbox']
        tbox = serializer.validated_data['tbox']
        convex_hull = serializer.validated_data['convex_hull']
        response_format = serializer.validated_data['response_format']
        placename = serializer.validated_data['placename']
        gazetteer = serializer.validated_data['gazetteer']

        temp_path = None

        try:
            # Check file size
            max_size_bytes = settings.GEOEXTENT_MAX_FILE_SIZE_MB * 1024 * 1024
            if uploaded_file.size > max_size_bytes:
                return Response(
                    {
                        'success': False,
                        'error': 'File too large',
                        'details': f'File size ({uploaded_file.size} bytes) exceeds maximum ({max_size_bytes} bytes)'
                    },
                    status=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE
                )

            # Save uploaded file
            temp_path = self._save_uploaded_file(uploaded_file)

            # Check if the file is a ZIP archive
            is_zip = zipfile.is_zipfile(temp_path)
            temp_dir = None

            if is_zip:
                # Extract ZIP to temporary directory and process with from_directory
                temp_dir = tempfile.mkdtemp(prefix='geoextent_zip_')
                logger.info(f"Extracting ZIP file to: {temp_dir}")

                with zipfile.ZipFile(temp_path, 'r') as zip_ref:
                    zip_ref.extractall(temp_dir)

                # Call geoextent.from_directory on extracted contents
                geoextent_result = geoextent.from_directory(
                    temp_dir,
                    bbox=bbox,
                    tbox=tbox,
                    convex_hull=convex_hull,
                    placename=gazetteer if placename else None,
                    show_progress=False,  # Disable progress bar in API
                    recursive=True,  # Process subdirectories in ZIP
                )
            else:
                # Call geoextent once with all parameters
                # placename parameter: None, 'nominatim', 'geonames', or 'photon'
                geoextent_result = geoextent.from_file(
                    temp_path,
                    bbox=bbox,
                    tbox=tbox,
                    convex_hull=convex_hull,
                    placename=gazetteer if placename else None,
                    show_progress=False,  # Disable progress bar in API
                )

            # Process result to structured format
            structured_result = self._process_geoextent_result(geoextent_result)

            # Check if processing failed
            if structured_result is None:
                return Response({
                    'error': f'Could not extract spatial extent from "{uploaded_file.name}". The file may not contain valid spatial data or may be in an unsupported format.'
                }, status=status.HTTP_400_BAD_REQUEST)

            structured_result['filename'] = uploaded_file.name

            # Format response based on requested format
            result = self._format_response(
                geoextent_result,
                structured_result,
                response_format,
                identifiers=[uploaded_file.name]
            )

            return Response(result, status=status.HTTP_200_OK)

        except Exception as e:
            logger.error(f"Error processing file extraction: {e}", exc_info=True)
            return Response(
                {
                    'success': False,
                    'error': 'Processing error',
                    'details': str(e)
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
        finally:
            # Cleanup temp file
            if temp_path:
                self._cleanup_temp_file(temp_path)
            # Cleanup temp directory if ZIP was extracted
            if 'temp_dir' in locals() and temp_dir and os.path.exists(temp_dir):
                try:
                    shutil.rmtree(temp_dir)
                    logger.info(f"Cleaned up temp directory: {temp_dir}")
                except Exception as e:
                    logger.warning(f"Failed to cleanup temp directory {temp_dir}: {e}")

    @extend_schema(
        summary="Extract spatial / temporal extent from a remote DOI or URL",
        description=(
            "Resolves the identifier(s) against supported repositories "
            "(Zenodo, PANGAEA, OSF, Figshare, Dryad, GFZ, Dataverse) and runs the "
            "[geoextent](https://nuest.github.io/geoextent/) Python library on the "
            "downloaded files. Supports a list of identifiers via JSON POST or a "
            "comma-separated `?identifiers=…` query parameter."
        ),
        tags=["Geoextent"],
        request=GeoextentRemoteSerializer,
        responses={
            200: OpenApiResponse(OpenApiTypes.OBJECT, description="Combined extent across all resolved identifiers."),
            400: OpenApiResponse(_ERROR_RESPONSE, description="Invalid identifier(s) or request body."),
            500: OpenApiResponse(_ERROR_RESPONSE, description="Resolver or extraction error."),
        },
    )
    @action(detail=False, methods=['get', 'post'], url_path='extract-remote')
    def extract_remote(self, request):
        """
        Extract geospatial and temporal extent from one or more remote repositories.

        POST /api/v1/geoextent/extract-remote/ - JSON body with identifiers array
        GET /api/v1/geoextent/extract-remote/?identifiers=doi1,doi2 - URL parameters with comma-separated identifiers
        """
        # Use different serializers for GET vs POST
        if request.method == 'GET':
            serializer = GeoextentRemoteGetSerializer(data=request.query_params)
        else:
            serializer = GeoextentRemoteSerializer(data=request.data)

        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        identifiers = serializer.validated_data['identifiers']
        bbox = serializer.validated_data['bbox']
        tbox = serializer.validated_data['tbox']
        convex_hull = serializer.validated_data['convex_hull']
        response_format = serializer.validated_data['response_format']
        placename = serializer.validated_data['placename']
        gazetteer = serializer.validated_data['gazetteer']
        file_limit = serializer.validated_data['file_limit']
        size_limit_mb = serializer.validated_data['size_limit_mb']
        external_metadata = serializer.validated_data['external_metadata']
        external_metadata_method = serializer.validated_data['external_metadata_method']

        try:
            workers = settings.GEOEXTENT_DOWNLOAD_WORKERS

            # Pass identifiers as list or string to geoextent.from_remote
            # It will handle combining extents natively
            geoextent_input = identifiers[0] if len(identifiers) == 1 else identifiers

            # Call geoextent once with all identifiers
            geoextent_result = geoextent.from_remote(
                geoextent_input,
                bbox=bbox,
                tbox=tbox,
                convex_hull=convex_hull,
                details=True,  # Get individual results
                placename=gazetteer if placename else None,
                max_download_workers=workers,
                max_download_size=f"{size_limit_mb}MB" if size_limit_mb else None,
                show_progress=False,  # Disable progress bar in API
                download_skip_nogeo=True,  # Skip non-geospatial files
                ext_metadata=external_metadata,
                ext_metadata_method=external_metadata_method,
            )

            # For single identifier, geoextent returns simple format
            if len(identifiers) == 1:
                structured_result = self._process_geoextent_result(geoextent_result)

                # Check if processing failed
                if structured_result is None:
                    return Response({
                        'error': f'Could not extract spatial extent from "{identifiers[0]}". The resource may not contain valid spatial data or may be inaccessible.'
                    }, status=status.HTTP_400_BAD_REQUEST)

                structured_result['identifier'] = identifiers[0]
                formatted_result = self._format_response(
                    geoextent_result,
                    structured_result,
                    response_format,
                    identifiers=identifiers
                )
                return Response(formatted_result, status=status.HTTP_200_OK)

            # For multiple identifiers, geoextent returns remote_bulk format
            # Extract individual results from details
            individual_results = []
            if 'details' in geoextent_result:
                for identifier, file_result in geoextent_result['details'].items():
                    # Check if this result has an error
                    if 'error' in file_result:
                        individual_results.append({
                            'identifier': identifier,
                            'success': False,
                            'error': file_result['error']
                        })
                        continue

                    structured_result = self._process_geoextent_result(file_result)
                    structured_result['identifier'] = identifier

                    # Format based on response_format
                    formatted_result = self._format_response(
                        file_result,
                        structured_result,
                        response_format,
                        identifiers=[identifier]
                    )
                    if response_format not in ['geojson', 'wkt', 'wkb']:
                        formatted_result['identifier'] = identifier

                    individual_results.append(formatted_result)

            # Build response with combined extent (geoextent always combines)
            combined_structured = self._process_geoextent_result(geoextent_result)
            combined_formatted = self._format_response(
                geoextent_result,
                combined_structured,
                response_format,
                identifiers=identifiers
            )

            # For multiple identifiers, return structured response with combined + individual
            # For GeoJSON format, return FeatureCollection with all features
            if response_format == 'geojson':
                # Merge all features into single FeatureCollection
                all_features = []
                if isinstance(combined_formatted, dict) and 'features' in combined_formatted:
                    all_features = combined_formatted['features'].copy()

                # Add individual features
                for result in individual_results:
                    if isinstance(result, dict) and 'features' in result:
                        all_features.extend(result['features'])

                response_data = {
                    'type': 'FeatureCollection',
                    'features': all_features,
                    'geoextent_extraction': combined_formatted.get('geoextent_extraction', {})
                }
            else:
                # For WKT/WKB, return combined with metadata
                response_data = combined_formatted

            return Response(response_data, status=status.HTTP_200_OK)

        except Exception as e:
            logger.error(f"Error processing remote extraction: {e}", exc_info=True)
            return Response(
                {'error': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    @extend_schema(
        summary="Extract a combined spatial / temporal extent from multiple uploaded files",
        description=(
            "Wraps the [geoextent](https://nuest.github.io/geoextent/) Python library, "
            "running it across every uploaded file and merging the extents."
        ),
        tags=["Geoextent"],
        request=GeoextentBatchSerializer,
        responses={
            200: OpenApiResponse(OpenApiTypes.OBJECT, description="Combined extent across all uploaded files plus per-file features."),
            400: OpenApiResponse(_ERROR_RESPONSE, description="Invalid request body or no spatial data extracted from any file."),
            413: OpenApiResponse(_ERROR_RESPONSE, description=f"Total upload size exceeds OPTIMAP_GEOEXTENT_MAX_BATCH_SIZE_MB."),
            500: OpenApiResponse(_ERROR_RESPONSE, description="Processing error inside the geoextent library."),
        },
    )
    @action(detail=False, methods=['post'], url_path='extract-batch')
    def extract_batch(self, request):
        """
        Extract geospatial and temporal extent from multiple uploaded files.

        POST /api/v1/geoextent/extract-batch/
        """
        serializer = GeoextentBatchSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        bbox = serializer.validated_data['bbox']
        tbox = serializer.validated_data['tbox']
        convex_hull = serializer.validated_data['convex_hull']
        response_format = serializer.validated_data['response_format']
        placename = serializer.validated_data['placename']
        gazetteer = serializer.validated_data['gazetteer']
        size_limit_mb = serializer.validated_data['size_limit_mb']

        # Get uploaded files from request
        files = request.FILES.getlist('files')
        if not files:
            return Response(
                {
                    'success': False,
                    'error': 'No files provided',
                    'details': 'At least one file must be uploaded'
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        temp_dir = None

        try:
            # Check total size
            total_size = sum(f.size for f in files)
            max_size_bytes = size_limit_mb * 1024 * 1024
            if total_size > max_size_bytes:
                return Response(
                    {
                        'success': False,
                        'error': 'Total size exceeds limit',
                        'details': f'Total size ({total_size} bytes) exceeds limit ({max_size_bytes} bytes)'
                    },
                    status=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE
                )

            # Create a temporary directory for all uploaded files
            temp_dir = tempfile.mkdtemp(prefix='geoextent_batch_')
            logger.info(f"Created temp directory for batch processing: {temp_dir}")

            # Save all files to the temporary directory
            for uploaded_file in files:
                temp_path = os.path.join(temp_dir, uploaded_file.name)
                with open(temp_path, 'wb') as destination:
                    for chunk in uploaded_file.chunks():
                        destination.write(chunk)
                logger.debug(f"Saved {uploaded_file.name} to {temp_path}")

            # Use geoextent.from_directory to process all files at once
            # details=True provides individual file results
            geoextent_result = geoextent.from_directory(
                temp_dir,
                bbox=bbox,
                tbox=tbox,
                convex_hull=convex_hull,
                details=True,  # Get individual file details
                placename=gazetteer if placename else None,
                show_progress=False,  # Disable progress bar in API
                recursive=False,  # Don't traverse subdirectories
            )

            # Process combined result
            combined_structured = self._process_geoextent_result(geoextent_result)

            # Check if processing failed for combined result
            if combined_structured is None:
                filenames = ', '.join([f.name for f in files])
                return Response({
                    'success': False,
                    'error': f'Could not extract spatial extent from the uploaded files: {filenames}',
                    'details': 'The files may not contain valid spatial data or may be in unsupported formats.'
                }, status=status.HTTP_400_BAD_REQUEST)

            # Process individual file results from details
            individual_results = []
            if 'details' in geoextent_result:
                for filename, file_result in geoextent_result['details'].items():
                    structured_result = self._process_geoextent_result(file_result)

                    # Skip files that failed processing
                    if structured_result is None:
                        logger.warning(f"Could not extract extent from {filename}")
                        individual_results.append({
                            'filename': filename,
                            'error': 'Could not extract spatial extent',
                            'details': 'The file may not contain valid spatial data or may be in an unsupported format.'
                        })
                        continue

                    structured_result['filename'] = filename

                    # Format based on response_format
                    formatted_result = self._format_response(
                        file_result,
                        structured_result,
                        response_format,
                        identifiers=[filename]
                    )
                    if response_format not in ['geojson', 'wkt', 'wkb']:
                        formatted_result['filename'] = filename

                    individual_results.append(formatted_result)

            # Build response with combined extent (geoextent always combines)
            filenames = [f.name for f in files]
            combined_formatted = self._format_response(
                geoextent_result,
                combined_structured,
                response_format,
                identifiers=filenames
            )

            response_data = {
                'success': True,
                'files_processed': len(files),
                'combined_extent': combined_formatted,
                'individual_results': individual_results
            }

            return Response(response_data, status=status.HTTP_200_OK)

        except Exception as e:
            logger.error(f"Error processing batch extraction: {e}", exc_info=True)
            return Response(
                {
                    'success': False,
                    'error': 'Processing error',
                    'details': str(e)
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
        finally:
            # Cleanup temporary directory and all files
            if temp_dir and os.path.exists(temp_dir):
                try:
                    shutil.rmtree(temp_dir)
                    logger.info(f"Cleaned up temp directory: {temp_dir}")
                except Exception as e:
                    logger.error(f"Error cleaning up temp directory {temp_dir}: {e}")
