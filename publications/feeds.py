from django.contrib.syndication.views import Feed
from django.utils.feedgenerator import Rss201rev2Feed, Atom1Feed
from .models import Publication
from datetime import datetime


class GeoRSSFeed(Feed):
    title = "Latest Publications (GeoRSS)"
    link = "/feeds/georss/"
    description = "Updates on the latest publications with geographic data."
    feed_type = Rss201rev2Feed

    def items(self):
        return Publication.objects.filter(status="p", geometry__isnull=False, url__isnull=False).order_by('-creationDate')[:10]

    def item_title(self, item):
        return item.title or "Untitled Publication"

    def item_description(self, item):
        return item.abstract or "No abstract available."

    def item_link(self, item):
        return item.url 


    def item_pubdate(self, item):
        if item.publicationDate:
            return datetime.combine(item.publicationDate, datetime.min.time())
        return item.creationDate

    def item_extra_kwargs(self, item):
        if item.geometry:
            if item.geometry.geom_type == "Polygon":
                coords = " ".join(
                    f"{pt[1]} {pt[0]}" for pt in item.geometry.coords[0]
                )  
                return {"georss:polygon": coords}
            elif item.geometry.geom_type == "Point":
                return {"georss:point": f"{item.geometry.y} {item.geometry.x}"}
        return {}


class GeoAtomFeed(Feed):
    title = "Latest Publications (GeoAtom)"
    link = "/feeds/geoatom/"
    description = "Updates on the latest publications with geographic data."
    feed_type = Atom1Feed

    def items(self):
        return Publication.objects.filter(status="p", geometry__isnull=False, url__isnull=False).order_by('-creationDate')[:10]

    def item_title(self, item):
        return item.title or "Untitled Publication"

    def item_description(self, item):
        return item.abstract or "No abstract available."

    def item_link(self, item):
        return item.url

    def item_pubdate(self, item):
        if item.publicationDate:
            return datetime.combine(item.publicationDate, datetime.min.time())
        return item.creationDate

    def item_extra_kwargs(self, item):
        if item.geometry:
            if item.geometry.geom_type == "Polygon":
                coords = " ".join(
                    f"{pt[1]} {pt[0]}" for pt in item.geometry.coords[0]
                )
                return {"georss:polygon": coords}
            elif item.geometry.geom_type == "Point":
                return {"georss:point": f"{item.geometry.y} {item.geometry.x}"}
        return {}



class W3CGeoFeed(Feed):
    title = "Latest Publications (W3CGeo)"
    link = "/feeds/w3cgeo/"
    description = "Updates on the latest publications with W3C Geo data."
    feed_type = Rss201rev2Feed

    def items(self):
        return Publication.objects.filter(status="p", geometry__isnull=False, url__isnull=False).order_by('-creationDate')[:10]

    def item_title(self, item):
        return item.title or "Untitled Publication"

    def item_description(self, item):
        return item.abstract or "No abstract available."

    def item_link(self, item):
        return item.url 

    def item_pubdate(self, item):
        if item.publicationDate:
            return datetime.combine(item.publicationDate, datetime.min.time())
        return item.creationDate

    def item_extra_kwargs(self, item):
        if item.geometry and item.geometry.geom_type == "Point":
            return {
                "geo:lat": str(item.geometry.y),  
                "geo:long": str(item.geometry.x),  
            }
        return {}
