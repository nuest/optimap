from django.contrib import admin
from leaflet.admin import LeafletGeoAdmin
from publications.models import Publication, Source, HarvestingEvent
from import_export.admin import ImportExportModelAdmin
from publications.tasks import harvest_oai_endpoint  
from django_q.models import Schedule
from django.utils.timezone import now

@admin.action(description="Mark selected publications as published")
def make_public(modeladmin, request, queryset):
    queryset.update(status="p")

@admin.action(description="Mark selected publications as draft (unpublished)")
def make_draft(modeladmin, request, queryset):
    queryset.update(status="d")

@admin.action(description="Trigger harvesting for selected sources")
def trigger_harvesting_for_specific(modeladmin, request, queryset):
    for source in queryset:
        harvest_oai_endpoint(source.id)  

@admin.action(description="Trigger harvesting for all sources")
def trigger_harvesting_for_all(modeladmin, request, queryset):
    all_sources = Source.objects.all()
    for source in all_sources:
        harvest_oai_endpoint(source.id) 

@admin.action(description="Schedule harvesting for selected sources")
def schedule_harvesting(modeladmin, request, queryset):
    """Admin action to manually schedule harvesting via Django-Q."""
    for source in queryset:
        existing_schedule = Schedule.objects.filter(name=f"Manual Harvest Source {source.id}")
        if existing_schedule.exists():
            modeladmin.message_user(request, f"Harvesting is already scheduled for Source {source.id}. Skipping.")
            continue  # Skip if already scheduled

        Schedule.objects.create(
            func='publications.tasks.harvest_oai_endpoint',
            args=str(source.id),
            schedule_type=Schedule.ONCE,
            next_run=now(),
            name=f"Manual Harvest Source {source.id}",
        )
        modeladmin.message_user(request, f"Harvesting scheduled for {queryset.count()} sources!")

@admin.register(Publication)
class PublicationAdmin(LeafletGeoAdmin, ImportExportModelAdmin):
    """Publication Admin."""

    list_display = ("doi", "creationDate", "lastUpdate", "created_by", "updated_by", "status", "provenance")

    actions = [make_public,make_draft]

@admin.register(Source)
class SourceAdmin(admin.ModelAdmin):
    list_display = ("id", "url_field", "harvest_interval_minutes", "last_harvest")
    list_filter = ("harvest_interval_minutes",)
    search_fields = ("url_field",)
    actions = [trigger_harvesting_for_specific,trigger_harvesting_for_all, schedule_harvesting]

@admin.register(HarvestingEvent)
class HarvestingEventAdmin(admin.ModelAdmin):
    list_display = ("id", "source", "status", "started_at", "completed_at")
    list_filter = ("status", "started_at", "completed_at")
    search_fields = ("source__url",)

