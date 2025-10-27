from django.contrib.sitemaps import Sitemap
from .models import Publication
from django.urls import reverse


class PublicationsSitemap(Sitemap): # based on django.contrib.sitemaps.GenericSitemap

    priority = 0.5
    changefreq = "weekly"
    queryset = Publication.objects.all().filter(status="p")
    protocol = None

    def items(self):
        items = self.queryset.filter()
        # items.count()
        return items

    def location(self, item):
        """Return the URL path for a publication (without domain)."""
        # Return only the path, not the full URL (Django's sitemap adds domain)
        if item.doi:
            return reverse("optimap:article-landing", args=[item.doi])
        else:
            return f"/work/{item.id}/"

    def lastmod(self, item):
        """Return the last modification date of the publication."""
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