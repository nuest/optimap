"""publications API views."""

from rest_framework import viewsets
from rest_framework_gis import filters
from rest_framework_gis.filters import InBBoxFilter, DistanceToPointFilter

from publications.models import Publication, Subscription, Journal
from publications.serializers import (
    PublicationSerializer,
    SubscriptionSerializer,
    JournalSerializer,
)

class PublicationViewSet(viewsets.ReadOnlyModelViewSet):
    """Publication view set with bounding‐box filtering on location."""
    queryset = Publication.objects.filter(status="p")
    serializer_class = PublicationSerializer

 # filter on the GeoDjango PointField called `geometry`
    bbox_filter_field = "geometry"
    filter_backends = (filters.InBBoxFilter,)


class SubscriptionViewset(viewsets.ModelViewSet):
    """Subscription CRUD for the current user, also bbox‐filtered."""
    serializer_class = SubscriptionSerializer

    bbox_filter_field = "geometry"
    filter_backends = (filters.InBBoxFilter,)

    def get_queryset(self):
        return Subscription.objects.filter(user=self.request.user)


class JournalViewSet(viewsets.ReadOnlyModelViewSet):
    """Read-only API for Journal resources with spatial filtering on geometry."""
    queryset = Journal.objects.all()
    serializer_class = JournalSerializer

    # Enable both bbox and distance filters on the 'geometry' field:
    bbox_filter_field = "geometry"
    distance_filter_field = "geometry"
    distance_filter_convert_meters = True
    filter_backends = (
        filters.InBBoxFilter,     # for ?in_bbox=minx,miny,maxx,maxy
        DistanceToPointFilter,    # for ?dist=1000&point=lon,lat
    )
