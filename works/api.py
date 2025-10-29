"""Publications API URL Configuration."""

from rest_framework import routers
from works.viewsets import (
    SourceViewSet,
    WorkViewSet,
    SubscriptionViewSet,
    GeoextentViewSet,
)

router = routers.DefaultRouter()
router.register(r"sources", SourceViewSet, basename="source")
router.register(r"works", WorkViewSet, basename="work")
router.register(r"subscriptions", SubscriptionViewSet, basename="subscription")
router.register(r"geoextent", GeoextentViewSet, basename="geoextent")

urlpatterns = router.urls
