# SPDX-FileCopyrightText: 2022 OPTIMETA and KOMET projects <https://projects.tib.eu/komet>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Publications API URL Configuration."""

from rest_framework import routers
from works.viewsets import (
    SourceViewSet,
    WorkViewSet,
    SubscriptionViewSet,
    GlobalRegionViewSet,
    GeoextentViewSet,
)

router = routers.DefaultRouter()
router.register(r"sources", SourceViewSet, basename="source")
router.register(r"works", WorkViewSet, basename="work")
router.register(r"subscriptions", SubscriptionViewSet, basename="subscription")
router.register(r"global-regions", GlobalRegionViewSet, basename="global-region")
router.register(r"geoextent", GeoextentViewSet, basename="geoextent")

urlpatterns = router.urls
