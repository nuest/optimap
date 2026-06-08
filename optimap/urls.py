# SPDX-FileCopyrightText: 2022 OPTIMETA and KOMET projects <https://projects.tib.eu/komet>
# SPDX-License-Identifier: GPL-3.0-or-later

"""OPTIMAP URL Configuration

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/4.0/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path, re_path, include
from django.contrib.sitemaps import views as sitemaps_views
from django.conf import settings
from optimap.sitemaps import WorksSitemap, StaticViewSitemap, FeedsSitemap, CollectionsSitemap
from optimap.views import RobotsView

sitemaps = {
    "static": StaticViewSitemap,
    "works": WorksSitemap,
    "feeds": FeedsSitemap,
    "collections": CollectionsSitemap,
}

urlpatterns = [
    path('admin/', admin.site.urls),
    path(
        "sitemap.xml",
        sitemaps_views.index,
        {"sitemaps": sitemaps},
        name="django.contrib.sitemaps.views.index",
    ),
    path(
        "sitemap-<section>.xml",
        sitemaps_views.sitemap,
        {"sitemaps": sitemaps},
        name="django.contrib.sitemaps.views.sitemap",
    ),
    re_path(r'^robots.txt', RobotsView.as_view(), name="robots_file"),
]

# OGC API - Features via pygeoapi at /ogcapi/ — registered before works.urls to
# prevent the <slug:short_slug> catch-all in works/urls.py from intercepting it.
if getattr(settings, 'PYGEOAPI_ENABLED', False):
    from pathlib import Path as _Path
    from django.views.static import serve as _static_serve
    import pygeoapi as _pygeoapi_pkg
    _pygeoapi_static = str(_Path(_pygeoapi_pkg.__file__).parent / 'static')
    urlpatterns += [
        re_path(r'^ogcapi/static/(?P<path>.*)$', _static_serve,
                {'document_root': _pygeoapi_static}),
    ]
    urlpatterns += [path("ogcapi/", include("pygeoapi.django_.urls"))]

# Main app URLs — must come AFTER the ogcapi prefix so the slug catch-all
# in works/urls.py doesn't shadow /ogcapi/.
urlpatterns += [
    path('', include(('works.urls', 'optimap'), namespace='optimap')),
]

# Custom error handlers
handler404 = 'optimap.views.custom_404'
handler500 = 'optimap.views.custom_500'

# Context processor for the site
from django.contrib.sites.shortcuts import get_current_site
from django.utils.functional import SimpleLazyObject

def site(request):
    protocol = 'https' if request.is_secure() else 'http'
    site = SimpleLazyObject(lambda: "{0}://{1}".format(protocol, get_current_site(request)))
    return {'site': site}
