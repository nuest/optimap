"""publications serializers."""

from rest_framework_gis.serializers import GeoFeatureModelSerializer
from rest_framework import serializers
from django.contrib.auth import get_user_model

from publications.models import Publication, Subscription, Journal

User = get_user_model()


class PublicationSerializer(GeoFeatureModelSerializer):
    """Publication GeoJSON serializer."""

    class Meta:
        model = Publication
        fields = ("id", "title" ,"abstract", "publicationDate", "url", "doi", "creationDate", "lastUpdate", "timeperiod_startdate", "timeperiod_enddate")
        geo_field = "geometry"
        auto_bbox = True


class SubscriptionSerializer(GeoFeatureModelSerializer):
    """Subscription GeoJSON serializer."""

    class Meta:
        model = Subscription
        fields = ("search_term","timeperiod_startdate","timeperiod_enddate","user_name")
        geo_field = "region"
        auto_bbox = True
        
class EmailChangeSerializer(serializers.ModelSerializer):
    """Handles email change requests."""

    class Meta:
        model = User
        fields = ['email']

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
        """Ensure deleted users are excluded from serialization."""
        if instance.deleted:  
            return None 
        return super().to_representation(instance)


class JournalSerializer(serializers.ModelSerializer):
    """Serializer for Journal resources."""

    class Meta:
        model = Journal
        fields = [
            "display_name",
            "issn_l",
            "issn_list",
            "publisher",
            "openalex_id",
        ]

    def validate_issn_l(self, value):
        """Validate ISSN-L format using python-stdnum."""
        from stdnum.issn import is_valid as is_valid_issn

        if value and not is_valid_issn(value):
            raise serializers.ValidationError("Invalid ISSN-L format")
        return value
