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

    def lastmod(self, item):
        item.lastUpdate

class StaticViewSitemap(Sitemap):
    priority = 0.5
    changefreq = "monthly"

    def items(self):
        return ["main",
                "data_and_api",
                "api",
                "privacy"]

    def location(self, item):
        return reverse(f"optimap:{item}") 