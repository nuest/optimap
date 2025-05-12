"""publications API views."""

from rest_framework import viewsets
from rest_framework_gis import filters

from publications.models import Publication, Subscription, Journal
from publications.serializers import (
    PublicationSerializer,
    SubscriptionSerializer,
    JournalSerializer,
)

class PublicationViewSet(viewsets.ReadOnlyModelViewSet):
    """publication view set."""

    bbox_filter_field = "location"
    filter_backends = (filters.InBBoxFilter,)
    queryset = Publication.objects.filter(status="p")
    serializer_class = PublicationSerializer

class SubscriptionViewset(viewsets.ModelViewSet):

    bbox_filter_field = "location"
    filter_backends = (filters.InBBoxFilter,)
    serializer_class = SubscriptionSerializer

    def get_queryset(self):
        # Only return subscriptions belonging to the logged-in user
        return Subscription.objects.filter(user=self.request.user)

class JournalViewSet(viewsets.ReadOnlyModelViewSet):
    """Read-only API for Journal resources."""

    queryset = Journal.objects.all()
    serializer_class = JournalSerializer
