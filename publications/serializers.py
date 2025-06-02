"""publications serializers."""

from rest_framework import serializers
from rest_framework_gis import serializers as gis_serializers
from django.contrib.auth import get_user_model

from rest_framework_gis.serializers import GeoFeatureModelSerializer
from .models import Publication, Subscription, Journal

User = get_user_model()


class PublicationSerializer(gis_serializers.GeoFeatureModelSerializer):
    """Publication GeoJSON serializer."""

    class Meta:
        model = Publication
        geo_field    = "geometery"
        auto_bbox    = True
        fields = (
            "id",
            "title",
            "abstract",
            "publicationDate",
            "url",
            "doi",
            "creationDate",
            "lastUpdate",
            "timeperiod_startdate",
            "timeperiod_enddate",
            "source",       # journal name
            "issn_l",       # journal ISSN-L
            "journal_url",  # journal OpenAlex URL
        )

class SubscriptionSerializer(gis_serializers.GeoFeatureModelSerializer):
    """Subscription GeoJSON serializer."""

    class Meta:
        model = Subscription
        fields = (
            "search_term",
            "timeperiod_startdate",
            "timeperiod_enddate",
            "user",
        )
        geo_field = "region"
        auto_bbox = True


class JournalSerializer(gis_serializers.GeoFeatureModelSerializer):
    """
    Returns each Journal as a GeoJSON Feature, using the 'geometry' field
    on Journal for the Feature.geometry member.
    """
    class Meta:
        model = Journal
        geo_field = "geometry"          
        id_field = False                
        fields = (
            "display_name",
            "issn_l",
            "issn_list",
            "publisher",
            "openalex_id",
            "articles",
        )
    def validate_issn_l(self, value):
        from stdnum.issn import is_valid as is_valid_issn

        if value and not is_valid_issn(value):
            raise serializers.ValidationError("Invalid ISSN-L format")
        return value


class EmailChangeSerializer(serializers.ModelSerializer):
    """Handles email change requests."""

    class Meta:
        model = User
        fields = ["email"]

    def validate_email(self, value):
        """Ensure the new email is not already in use."""
        if User.objects.filter(email=value).exists():
            raise serializers.ValidationError("This email is already registered.")
        return value

class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["id", "username", "email"]

    def to_representation(self, instance):
        if getattr(instance, "deleted", False):
            return None
        return super().to_representation(instance)
