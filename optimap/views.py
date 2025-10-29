"""
General site views.

This module handles:
- Homepage
- Static pages (about, accessibility, privacy)
- Data page
- Geoextent tool
- Sitemaps
- Error pages
- Feeds list
"""

import logging
logger = logging.getLogger(__name__)

from django.shortcuts import render
from django.http import HttpResponse
from django.views.decorators.cache import never_cache
from django.views.generic import View
from django.conf import settings
import tempfile
from pathlib import Path
from datetime import datetime
from django.utils.timezone import get_default_timezone
import humanize
from works.models import GlobalRegion
from works import views_feeds
from works.feeds import normalize_region_slug
from django.urls import reverse
import geoextent.lib.features


def main(request):
    # Pass the 'next' parameter to template for login redirect
    next_url = request.GET.get('next', '')
    return render(request, "main.html", {'next': next_url})

def about(request):
    return render(request, 'about.html')

def accessibility(request):
    return render(request, 'accessibility.html')

def privacy(request):
    return render(request, 'privacy.html')

@never_cache

def data(request):
    """
    Renders the data page showing links and sizes for the latest dumps.
    """
    cache_dir = Path(tempfile.gettempdir()) / "optimap_cache"
    cache_dir.mkdir(exist_ok=True)

    # scan for existing dumps
    geojson_files = sorted(cache_dir.glob('optimap_data_dump_*.geojson'), reverse=True)
    gpkg_files    = sorted(cache_dir.glob('optimap_data_dump_*.gpkg'),   reverse=True)

    last_geo  = geojson_files[0] if geojson_files else None
    last_gzip = Path(str(last_geo) + ".gz") if last_geo else None
    last_gpkg = gpkg_files[0]    if gpkg_files    else None

    # — Supervisor check: ensure all dump file times are within 1 hour
    mtimes = []
    for p in (last_geo, last_gzip, last_gpkg):
        if p and p.exists():
            mtimes.append(p.stat().st_mtime)
    if mtimes and (max(mtimes) - min(mtimes) > 3600):
        ts_map = {
            p.name: datetime.fromtimestamp(p.stat().st_mtime, get_default_timezone())
            for p in (last_geo, last_gzip, last_gpkg) if p and p.exists()
        }
        logger.warning("Data dump timestamps differ by >1h: %s", ts_map)

    # humanized sizes
    geojson_size    = humanize.naturalsize(last_geo.stat().st_size, binary=True) if last_geo else None
    geopackage_size = humanize.naturalsize(last_gpkg.stat().st_size, binary=True) if last_gpkg else None

    # last updated timestamp (using JSON file)
    if last_geo:
        ts = last_geo.stat().st_mtime
        last_updated = datetime.fromtimestamp(ts, get_default_timezone())
    else:
        last_updated = None

    return render(request, 'data.html', {
        'geojson_size':    geojson_size,
        'geopackage_size': geopackage_size,
        'interval':        settings.DATA_DUMP_INTERVAL_HOURS,
        'last_updated':    last_updated,
        'last_geojson':    last_geo.name  if last_geo else None,
        'last_gpkg':       last_gpkg.name if last_gpkg else None,
    })

def feeds_list(request):
    """Display available predefined feeds grouped by global regions."""
    regions = GlobalRegion.objects.all().order_by("name")
    return render(request, "feeds.html", {"regions": regions})

def geoextent(request):
    """Geoextent extraction UI page."""
    from geoextent.lib.features import get_supported_features

    # Get supported formats and providers from geoextent's features API
    features = get_supported_features()

    # Organize file formats by handler type with display names
    supported_formats = []
    for handler in features.get('file_formats', []):
        display_name = handler.get('display_name', handler['handler'])
        extensions = [ext.lstrip('.') for ext in handler.get('file_extensions', [])]
        description = handler.get('description', '')
        if extensions:
            supported_formats.append({
                'name': display_name,
                'extensions': extensions,
                'description': description
            })

    # Extract provider details with descriptions and URLs
    supported_providers = []
    for provider in features.get('content_providers', []):
        supported_providers.append({
            'name': provider.get('name', 'Unknown'),
            'description': provider.get('description', ''),
            'website': provider.get('website', ''),
            'examples': provider.get('examples', [])
        })

    context = {
        'supported_formats': supported_formats,
        'supported_providers': supported_providers,
        'geoextent_version': features.get('version', 'unknown'),
        'max_file_size_mb': getattr(settings, 'GEOEXTENT_MAX_FILE_SIZE_MB', 100),
        'max_batch_size_mb': getattr(settings, 'GEOEXTENT_MAX_BATCH_SIZE_MB', 500),
        'max_download_size_mb': getattr(settings, 'GEOEXTENT_MAX_DOWNLOAD_SIZE_MB', 1000),
    }

    return render(request, 'geoextent.html', context)

class RobotsView(View):
    http_method_names = ['get']
    def get(self, request):

        # Build robots.txt content
        lines = [
            "User-Agent: *",
            "Disallow:",
            "",
            "# Sitemaps",
            f"Sitemap: {request.scheme}://{request.site.domain}/sitemap.xml",
            "",
            "# Feed URLs for indexing",
            "# Global feeds",
            f"Allow: {reverse('optimap:api-feed-georss')}",
            f"Allow: {reverse('optimap:api-feed-atom')}",
            "",
        ]

        # Add regional feeds
        regions = GlobalRegion.objects.all().order_by("region_type", "name")

        # Continents
        lines.append("# Continent feeds")
        for region in regions:
            if region.region_type == GlobalRegion.CONTINENT:
                slug = normalize_region_slug(region.name)
                lines.append(f"Allow: /feeds/continent/{slug}/")
                lines.append(f"Allow: /api/v1/feeds/continent/{slug}.rss")
                lines.append(f"Allow: /api/v1/feeds/continent/{slug}.atom")

        lines.append("")
        lines.append("# Ocean feeds")
        for region in regions:
            if region.region_type == GlobalRegion.OCEAN:
                slug = normalize_region_slug(region.name)
                lines.append(f"Allow: /feeds/ocean/{slug}/")
                lines.append(f"Allow: /api/v1/feeds/ocean/{slug}.rss")
                lines.append(f"Allow: /api/v1/feeds/ocean/{slug}.atom")

        content = "\n".join(lines)
        response = HttpResponse(content, content_type="text/plain")
        return response

def custom_404(request, exception=None):
    """Custom 404 error handler"""
    return render(request, '404.html', status=404)

def custom_500(request):
    """Custom 500 error handler"""
    return render(request, '500.html', status=500)

def feeds(request):

    global_feeds = [
        { "title": "Geo RSS",     "url": reverse("optimap:api-feed-georss")   },
        { "title": "Atom",        "url": reverse("optimap:api-feed-atom")     },
    ]

    regions = GlobalRegion.objects.all().order_by("region_type", "name")

    # Add normalized slugs to regions for URL generation
    regions_with_slugs = []
    for region in regions:
        slug = normalize_region_slug(region.name)
        region.normalized_slug = slug
        regions_with_slugs.append(region)

    return render(request, "feeds.html", {
        "global_feeds": global_feeds,
        "regions": regions_with_slugs,
    })


def sitemap_page(request):
    """Human-readable sitemap page"""
    return render(request, 'sitemap_page.html')
