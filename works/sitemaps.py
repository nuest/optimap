from django.contrib.sitemaps import Sitemap
from .models import Work, GlobalRegion
from django.urls import reverse


class WorksSitemap(Sitemap): # based on django.contrib.sitemaps.GenericSitemap

    priority = 0.5
    changefreq = "weekly"
    queryset = Work.objects.all().filter(status="p")
    protocol = None

    def items(self):
        items = self.queryset.filter()
        # items.count()
        return items

    def location(self, item):
        """Return the URL path for a work (without domain)."""
        # Return only the path, not the full URL (Django's sitemap adds domain)
        if item.doi:
            return reverse("optimap:article-landing", args=[item.doi])
        else:
            return f"/work/{item.id}/"

    def lastmod(self, item):
        """Return the last modification date of the work."""
        return item.lastUpdate

class StaticViewSitemap(Sitemap):
    priority = 0.5
    changefreq = "monthly"

    def items(self):
        return [
            "main",           # Home page (/)
            "about",          # About page (/about/)
            "accessibility",  # Accessibility statement (/accessibility/)
            "contribute",     # Contribute page (/contribute/)
            "data",           # Data download page (/data/)
            "feeds",          # RSS/Atom feeds listing (/feeds/)
            "geoextent",      # Geoextent extraction tool (/geoextent/)
            "privacy",        # Privacy policy (/privacy/)
            "redoc",          # API schema UI (/api/schema/ui/)
            "sitemap-page",   # Human-readable sitemap (/pages/)
            "works",          # Works listing (/works/)
        ]

    def location(self, item):
        return reverse(f"optimap:{item}")

class FeedsSitemap(Sitemap):
    """Sitemap for global regional feeds (continents and oceans)."""
    priority = 0.6
    changefreq = "daily"

    def items(self):
        """Return all GlobalRegion objects (continents and oceans)."""
        return GlobalRegion.objects.all().order_by('region_type', 'name')

    def location(self, obj):
        """Return the feed page URL for each region."""
        return obj.get_absolute_url()

    def lastmod(self, obj):
        """Return the last modification date."""
        return obj.last_loaded