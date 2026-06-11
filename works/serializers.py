# SPDX-FileCopyrightText: 2022 OPTIMETA and KOMET projects <https://projects.tib.eu/komet>
# SPDX-License-Identifier: GPL-3.0-or-later

"""publications serializers."""

from rest_framework import serializers
from rest_framework_gis.serializers import GeoFeatureModelSerializer
from rest_framework import serializers as drf_serializers
from drf_spectacular.utils import extend_schema_field, inline_serializer
from .models import Work, Subscription, Source, GlobalRegion, Collection
from django.contrib.auth import get_user_model
from django.conf import settings
from django.urls import reverse

User = get_user_model()

class SourceSerializer(serializers.ModelSerializer):
    openalex_url = serializers.ReadOnlyField()
    source_type_display = serializers.CharField(source="get_source_type_display", read_only=True)
    source_url = serializers.SerializerMethodField(
        help_text="Absolute URL to this source's entry in the OPTIMAP API.",
    )
    collection = serializers.SerializerMethodField(
        help_text="Default collection for works harvested from this source: identifier, name, and absolute API URL. Null if no collection is set.",
    )

    class Meta:
        model = Source
        fields = (
            "id",
            "name",
            "issn_l",
            "openalex_id",
            "openalex_url",
            "publisher_name",
            "works_count",
            "works_api_url",
            "default_work_type",
            "source_type",
            "source_type_display",
            "homepage_url",
            "abbreviated_title",
            "is_oa",
            "is_preprint",
            "source_url",
            "collection",
        )

    @extend_schema_field(serializers.URLField())
    def get_source_url(self, obj):
        request = self.context.get("request")
        path = f"/api/v1/sources/{obj.pk}/"
        return request.build_absolute_uri(path) if request else path

    @extend_schema_field(
        inline_serializer(
            name="SourceCollectionRef",
            fields={
                "identifier": serializers.CharField(),
                "name": serializers.CharField(),
                "collection_url": serializers.URLField(),
            },
            allow_null=True,
        )
    )
    def get_collection(self, obj):
        if not obj.collection_id:
            return None
        coll = obj.collection
        request = self.context.get("request")
        path = f"/api/v1/collections/{coll.identifier}/"
        coll_url = request.build_absolute_uri(path) if request else path
        return {
            "identifier": coll.identifier,
            "name": coll.name,
            "collection_url": coll_url,
        }



class WorkSerializer(GeoFeatureModelSerializer):
    source_details = serializers.SerializerMethodField(help_text="Embedded source row (same shape as `/api/v1/sources/<id>/`).")
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    bok_concepts_resolved = serializers.SerializerMethodField(
        help_text="Each BoK code resolved against the active EO4GEO BoK snapshot: code, name, uri, parent_code, breadcrumb, orphan flag."
    )

    class Meta:
        model = Work
        geo_field = "geometry"
        auto_bbox = True
        fields = [
            "id",
            "title",
            "type",
            "abstract",
            "publicationDate",
            "doi",
            "url",
            "timeperiod_startdate",
            "timeperiod_enddate",
            "placename",
            "country_code",
            "source_details",
            "status",
            "status_display",
            "authors",
            "keywords",
            "topics",
            "bok_concepts",
            "bok_concepts_resolved",
            "openalex_id",
            "openalex_match_info",
            "openalex_fulltext_origin",
            "openalex_is_retracted",
            "openalex_ids",
            "openalex_open_access_status",
        ]

    @extend_schema_field(SourceSerializer)
    def get_source_details(self, obj):
        source = obj.source
        if not source:
            return {}
        return SourceSerializer(source, context=self.context).data

    @extend_schema_field(serializers.ListField(child=serializers.DictField()))
    def get_bok_concepts_resolved(self, obj):
        codes = obj.bok_concepts or []
        if not codes:
            return []
        # Late import to avoid circular dependency at module load.
        from works.bok import client as bok_client
        try:
            return bok_client.resolve(codes)
        except Exception:
            # If the BoK snapshot is unreachable, fall back to bare codes
            # so the API stays responsive.
            return [
                {"code": c, "name": c, "uri": "", "parent_code": "",
                 "breadcrumb": [], "orphan": True}
                for c in codes
            ]

class SubscriptionSerializer(GeoFeatureModelSerializer):
    class Meta:
        model = Subscription
        fields = (
            "id",
            "user",
            "name",
            "search_term",
            "timeperiod_startdate",
            "timeperiod_enddate",
            "region",
            "subscribed",
        )

        geo_field = "region"
        auto_bbox = True


class EmailChangeSerializer(serializers.ModelSerializer):
    """Handles email change requests."""

    class Meta:
        model = User
        fields = ["email"]

    def validate_email(self, value):
        """Ensure the new email is not already in use."""
        value = value.lower().strip()
        if User.objects.filter(email=value).exists():
            raise drf_serializers.ValidationError("This email is already registered.")
        return value


class UserSerializer(drf_serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["id", "username", "email"]


# Geoextent API Serializers

# Shared field definitions
RESPONSE_FORMAT_CHOICES = ['geojson', 'wkt', 'wkb']
RESPONSE_FORMAT_DEFAULT = 'geojson'
RESPONSE_FORMAT_HELP = "Response format: 'geojson' (default - GeoJSON FeatureCollection), 'wkt' (WKT string with metadata), 'wkb' (WKB hex string with metadata)"

# All gazetteers the library supports.
GAZETTEER_CHOICES = ['nominatim', 'geonames', 'photon']
GAZETTEER_DEFAULT = 'nominatim'


def get_available_gazetteers():
    """Return gazetteers that are usable with the current configuration.

    GeoNames requires OPTIMAP_GEOEXTENT_GEONAMES_USERNAME to be set; if it is
    absent or empty the library raises ValueError at call time, so we exclude
    it here to give users a clean 400 / empty dropdown instead of a 500.
    """
    available = ['nominatim', 'photon']
    if getattr(settings, 'GEOEXTENT_GEONAMES_USERNAME', ''):
        available.append('geonames')
    return available


class GeoextentBaseSerializer(serializers.Serializer):
    """Base serializer with common geoextent parameters."""
    bbox = serializers.BooleanField(default=True)
    tbox = serializers.BooleanField(default=True)
    convex_hull = serializers.BooleanField(default=False)
    response_format = serializers.ChoiceField(
        choices=RESPONSE_FORMAT_CHOICES,
        default=RESPONSE_FORMAT_DEFAULT,
        help_text=RESPONSE_FORMAT_HELP
    )
    placename = serializers.BooleanField(default=False)
    gazetteer = serializers.ChoiceField(
        choices=GAZETTEER_CHOICES,
        default=GAZETTEER_DEFAULT
    )
    external_metadata = serializers.BooleanField(
        default=True,
        help_text="Retrieve external metadata from CrossRef/DataCite for DOIs (only applies to remote resources)"
    )
    external_metadata_method = serializers.ChoiceField(
        choices=['auto', 'all', 'crossref', 'datacite'],
        default='auto',
        help_text="Method for retrieving metadata: 'auto' (default), 'all', 'crossref', or 'datacite'"
    )

    def validate_gazetteer(self, value):
        """Reject unconfigured gazetteers before they reach the library."""
        available = get_available_gazetteers()
        if value not in available:
            raise serializers.ValidationError(
                f"Gazetteer '{value}' is not available. "
                f"Available options: {', '.join(available)}. "
                f"GeoNames requires OPTIMAP_GEOEXTENT_GEONAMES_USERNAME to be configured."
            )
        return value


class GeoextentExtractSerializer(GeoextentBaseSerializer):
    """Serializer for extracting extent from uploaded file."""
    file = serializers.FileField(required=True)


class GeoextentRemoteSerializer(GeoextentBaseSerializer):
    """Serializer for extracting extent from remote repository."""
    identifiers = serializers.ListField(
        child=serializers.CharField(),
        required=True,
        min_length=1,
        help_text="List of DOIs or repository URLs"
    )
    file_limit = serializers.IntegerField(default=10, min_value=1, max_value=100)
    size_limit_mb = serializers.IntegerField(default=100, min_value=1)

    def validate_size_limit_mb(self, value):
        """Ensure requested size doesn't exceed server maximum."""
        max_allowed = getattr(settings, 'GEOEXTENT_MAX_DOWNLOAD_SIZE_MB', 1000)
        if value > max_allowed:
            raise serializers.ValidationError(
                f"Requested size limit ({value}MB) exceeds server maximum ({max_allowed}MB)"
            )
        return value


class GeoextentRemoteGetSerializer(GeoextentBaseSerializer):
    """Serializer for GET endpoint with URL parameters."""
    identifiers = serializers.CharField(
        required=True,
        help_text="Comma-separated DOIs or repository URLs"
    )
    file_limit = serializers.IntegerField(default=10, min_value=1, max_value=100)
    size_limit_mb = serializers.IntegerField(default=100, min_value=1)

    def validate_identifiers(self, value):
        """Parse comma-separated identifiers and validate."""
        identifiers = [i.strip() for i in value.split(',') if i.strip()]
        if not identifiers:
            raise serializers.ValidationError("At least one identifier must be provided")
        return identifiers

    def validate_size_limit_mb(self, value):
        """Ensure requested size doesn't exceed server maximum."""
        max_allowed = getattr(settings, 'GEOEXTENT_MAX_DOWNLOAD_SIZE_MB', 1000)
        if value > max_allowed:
            raise serializers.ValidationError(
                f"Requested size limit ({value}MB) exceeds server maximum ({max_allowed}MB)"
            )
        return value


class GeoextentBatchSerializer(GeoextentBaseSerializer):
    """Serializer for extracting extent from multiple files."""
    # files handled separately in view
    size_limit_mb = serializers.IntegerField(default=100, min_value=1)

    def validate_size_limit_mb(self, value):
        """Ensure total batch size doesn't exceed server maximum."""
        max_allowed = getattr(settings, 'GEOEXTENT_MAX_BATCH_SIZE_MB', 500)
        if value > max_allowed:
            raise serializers.ValidationError(
                f"Requested batch size ({value}MB) exceeds server maximum ({max_allowed}MB)"
            )
        return value


class GeoextentExtractTextSerializer(serializers.Serializer):
    """Serializer for NER-based location extraction from free text."""
    text = serializers.CharField(
        required=True,
        max_length=20000,
        help_text="Free text (title, abstract, etc.) to extract place names from.",
    )
    gazetteer = serializers.ChoiceField(
        choices=GAZETTEER_CHOICES,
        default=None,
        allow_null=True,
        help_text="Gazetteer service for geocoding found place names. Defaults to OPTIMAP_GEOEXTENT_NER_GAZETTEER.",
    )
    ner_ambiguity = serializers.ChoiceField(
        choices=['drop', 'top'],
        default='drop',
        help_text=(
            "'drop' (default): skip place names that match multiple gazetteer candidates. "
            "'top': keep the highest-ranked candidate when multiple are returned."
        ),
    )
    tbox = serializers.BooleanField(
        default=True,
        help_text="Also extract temporal extent from date mentions in the text (enabled by default).",
    )
    convex_hull = serializers.BooleanField(
        default=False,
        help_text="Return convex hull of all matched places instead of bounding box.",
    )

    def validate_gazetteer(self, value):
        if value is None:
            value = getattr(settings, 'GEOEXTENT_NER_GAZETTEER', 'nominatim')
        available = get_available_gazetteers()
        if value not in available:
            raise serializers.ValidationError(
                f"Gazetteer '{value}' is not available. "
                f"Available options: {', '.join(available)}. "
                f"GeoNames requires OPTIMAP_GEOEXTENT_GEONAMES_USERNAME to be configured."
            )
        return value

    def validate_text(self, value):
        if not value or not value.strip():
            raise serializers.ValidationError("Text must not be empty.")
        return value


class GlobalRegionSerializer(GeoFeatureModelSerializer):
    """Serializer for GlobalRegion model with GeoJSON output."""
    region_type_display = serializers.CharField(source='get_region_type_display', read_only=True)
    slug = serializers.CharField(source='get_slug', read_only=True)
    absolute_url = serializers.CharField(source='get_absolute_url', read_only=True)

    class Meta:
        model = GlobalRegion
        geo_field = "geom"
        auto_bbox = True
        fields = [
            "id",
            "name",
            "region_type",
            "region_type_display",
            "slug",
            "absolute_url",
            "source_url",
            "license",
        ]


class CollectionSerializer(serializers.ModelSerializer):
    works_count = serializers.IntegerField(
        read_only=True,
        help_text="Number of published works in this collection.",
    )
    collection_url = serializers.SerializerMethodField(
        help_text="Absolute URL of the collection landing page.",
    )
    feeds = serializers.SerializerMethodField(
        help_text="GeoRSS and GeoAtom feed URLs for this collection.",
    )
    downloads = serializers.SerializerMethodField(
        help_text="Download URLs (GeoJSON, GeoPackage, CSV) for this collection.",
    )

    class Meta:
        model = Collection
        fields = [
            "id",
            "identifier",
            "short_slug",
            "name",
            "description",
            "homepage_url",
            "is_published",
            "created_at",
            "updated_at",
            "works_count",
            "collection_url",
            "feeds",
            "downloads",
        ]

    def _abs(self, url_name, slug):
        request = self.context.get("request")
        path = reverse(url_name, kwargs={"collection_slug": slug})
        return request.build_absolute_uri(path) if request else path

    @extend_schema_field(serializers.URLField())
    def get_collection_url(self, obj):
        return self._abs("optimap:collection-page", obj.identifier)

    @extend_schema_field({"type": "object", "properties": {
        "rss": {"type": "string", "format": "uri"},
        "atom": {"type": "string", "format": "uri"},
    }})
    def get_feeds(self, obj):
        return {
            "rss": self._abs("optimap:api-collection-georss", obj.identifier),
            "atom": self._abs("optimap:api-collection-atom", obj.identifier),
        }

    @extend_schema_field({"type": "object", "properties": {
        "geojson": {"type": "string", "format": "uri"},
        "gpkg": {"type": "string", "format": "uri"},
        "csv": {"type": "string", "format": "uri"},
    }})
    def get_downloads(self, obj):
        return {
            "geojson": self._abs("optimap:download-collection-geojson", obj.identifier),
            "gpkg": self._abs("optimap:download-collection-gpkg", obj.identifier),
            "csv": self._abs("optimap:download-collection-csv", obj.identifier),
        }
