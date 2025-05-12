"""Publications API URL Configuration."""

from rest_framework import routers

from publications.viewsets import PublicationViewSet, SubscriptionViewset, JournalViewSet

router = routers.DefaultRouter()
router.register(r"publications", PublicationViewSet)
router.register(r"subscriptions", SubscriptionViewset, basename="subscription")
router.register(r"journals", JournalViewSet, basename="journal")

urlpatterns = router.urls
