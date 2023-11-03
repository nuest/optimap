from django.contrib.gis.db import models
from django.contrib.postgres.fields import ArrayField
from django_currentuser.db.models import CurrentUserField

class Publication(models.Model):
    # required fields      
    doi = models.CharField(max_length=1024)
    
    # automatic fields
    creationDate = models.DateTimeField(auto_now_add=True)
    lastUpdate = models.DateTimeField(auto_now=True)
    # see useful hint at https://github.com/zsoldosp/django-currentuser/issues/69
    created_by = CurrentUserField(
        verbose_name=("Created by"),
        related_name="%(app_label)s_%(class)s_creator",
    )
    updated_by = CurrentUserField(
        verbose_name=("Updated by"),
        related_name="%(app_label)s_%(class)s_updater",
        on_update=True,
    )

    # possibly blank fields
    publicationDate = models.DateField(null=True,blank=True)
    abstract = models.TextField(null=True, blank=True)
    
    url = models.URLField(max_length=1024, null=True, blank=True)
    geometry = models.GeometryCollectionField(verbose_name='Publication geometry/ies', srid = 4326, null=True, blank=True)
    journal = models.CharField(max_length=1024, null=True, blank=True)
    timeperiod_startdate = ArrayField(models.DateField(null=True), null=True, blank=True)
    timeperiod_enddate = ArrayField(models.DateField(null=True), null=True, blank=True)

    def __str__(self):
        """Return string representation."""
        return self.doi

class Source(models.Model):
    # automatic fields
    creationDate = models.DateTimeField(auto_now_add=True)
    lastUpdate = models.DateTimeField(auto_now=True)
    created_by = CurrentUserField(
        verbose_name=("Created by"),
        related_name="%(app_label)s_%(class)s_creator",
    )
    updated_by = CurrentUserField(
        verbose_name=("Updated by"),
        related_name="%(app_label)s_%(class)s_updater",
        on_update=True,
    )

    url_field = models.URLField(max_length = 999)
    harvest_interval_minutes = models.IntegerField(default=60*24*3)
    last_harvest = models.DateTimeField(auto_now_add=True,null=True)
    
class Subscription(models.Model):
    name = models.CharField(max_length=4096)
    timeperiod_startdate = models.DateField(null=True)
    timeperiod_enddate = models.DateField(null=True)
    search_area = models.GeometryCollectionField(null=True, blank=True)
    user_name = models.CharField(max_length=4096)

    def __str__(self):
        """Return string representation."""
        return self.name

    class Meta:
        ordering = ['user_name']
        verbose_name = "subscription"