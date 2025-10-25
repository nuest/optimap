import logging
logger = logging.getLogger(__name__)

from django.contrib import admin, messages
from django.utils.html import format_html
from django.conf import settings
from django.core.mail import send_mail
from leaflet.admin import LeafletGeoAdmin
from publications.models import Publication, Source, HarvestingEvent, BlockedEmail, BlockedDomain, GlobalRegion
from import_export.admin import ImportExportModelAdmin
from publications.models import EmailLog, Subscription, UserProfile, WikidataExportLog
from publications.tasks import harvest_oai_endpoint, schedule_subscription_email_task, send_monthly_email, schedule_monthly_email_task
from django_q.models import Schedule
from django.utils.timezone import now
from publications.models import CustomUser
from publications.tasks import regenerate_geojson_cache
from publications.tasks import regenerate_geopackage_cache
from django.test import Client
from django.http import HttpResponse
from publications.wikidata import export_publications_to_wikidata, export_publications_to_wikidata_dryrun

@admin.action(description="Export selected publications to Wikidata/Wikibase")
def export_to_wikidata(modeladmin, request, queryset):
    stats = export_publications_to_wikidata(queryset)

    # Success messages
    if stats['created']:
        messages.success(request, f"{stats['created']} new Wikidata item(s) created.")
    if stats['updated']:
        messages.success(request, f"{stats['updated']} existing Wikidata item(s) updated.")
    if stats['skipped']:
        messages.info(request, f"{stats['skipped']} publication(s) skipped (already exist or duplicate labels).")

    # Error messages
    if stats['errors']:
        messages.error(request, f"{stats['errors']} publication(s) failed to export. Check the Wikidata export logs for details.")

    # Summary message
    messages.info(request, f"Total: {stats['total']} publication(s) processed.")

@admin.action(description="[DRY-RUN] Export selected publications to Wikidata/Wikibase")
def export_to_wikidata_dryrun(modeladmin, request, queryset):
    stats = export_publications_to_wikidata_dryrun(queryset)

    # Dry-run summary messages
    messages.info(request, f"[DRY-RUN] Export simulation complete:")

    if stats['created']:
        messages.info(request, f"  • Would create {stats['created']} new Wikidata item(s)")
    if stats['updated']:
        messages.info(request, f"  • Would update {stats['updated']} existing Wikidata item(s)")
    if stats['skipped']:
        messages.info(request, f"  • Would skip {stats['skipped']} publication(s)")
    if stats['errors']:
        messages.warning(request, f"  • {stats['errors']} publication(s) have validation errors")

    # Summary message
    messages.success(request, f"[DRY-RUN] Total: {stats['total']} publication(s) analyzed. No changes were written to Wikibase.")

@admin.action(description="Mark selected publications as published")
def make_public(modeladmin, request, queryset):
    queryset.update(status="p")

@admin.action(description="Mark selected publications as draft (unpublished)")
def make_draft(modeladmin, request, queryset):
    queryset.update(status="d")

@admin.action(description="Trigger harvesting for selected sources")
def trigger_harvesting_for_specific(modeladmin, request, queryset):
    return trigger_harvesting_for_set(queryset, request)
    
@admin.action(description="Trigger harvesting for all sources")
def trigger_harvesting_for_all(modeladmin, request, queryset):
    all_sources = Source.objects.all()
    return trigger_harvesting_for_set(all_sources, request)
    
def trigger_harvesting_for_set(sources, request):
    user = request.user

    for source in sources:
        added, spatial, temporal = harvest_oai_endpoint(source.id, user)
        logger.info(f"Harvested {added} publications from source {source.id} ({source.url_field}) of which {spatial} have spatial data and {temporal} have temporal data.")

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

@admin.action(description="Send Monthly Manuscript Email")
def trigger_monthly_email(modeladmin, request, queryset):
    """
    Admin action to trigger the email task manually.
    """
    try:
        send_monthly_email(trigger_source='admin', sent_by=request.user) 
        messages.success(request, "Monthly manuscript email has been sent successfully.")
    except Exception as e:
        messages.error(request, f"Failed to send email: {e}")

@admin.action(description="Schedule Monthly Email Task")
def trigger_monthly_email_task(modeladmin, request, queryset):
    """
    Admin action to manually schedule the email task.
    """
    try:        
        schedule_monthly_email_task(sent_by=request.user)  
        messages.success(request, "Monthly email task has been scheduled successfully.")
    except Exception as e:
        messages.error(request, f"Failed to schedule task: {e}")

@admin.action(description="Send subscription-based emails")
def send_subscription_emails(modeladmin, request, queryset):
    """
    Admin action to manually send subscription-based emails to selected users.
    """
    from publications.tasks import send_subscription_based_email

    selected_users = queryset.filter(subscribed=True).values_list('user', flat=True)
    if not selected_users:
        messages.warning(request, "No active subscribers selected.")
        return

    send_subscription_based_email(sent_by=request.user, user_ids=list(selected_users))
    messages.success(request, "Subscription-based emails have been sent.")

@admin.action(description="Schedule subscription-based Email Task")
def send_subscription_emails_scheduler(modeladmin, request, queryset):
    """
    Admin action to manually schedule the email task.
    """
    try:        
        schedule_subscription_email_task(sent_by=request.user)  
        messages.success(request, "Monthly email task has been scheduled successfully.")
    except Exception as e:
        messages.error(request, f"Failed to schedule task: {e}")


@admin.action(description="Delete user and block email")
def block_email(modeladmin, request, queryset):
    for user in queryset:
        BlockedEmail.objects.create(email=user.email) 
        user.delete()
    modeladmin.message_user(request, "Selected users have been deleted and their emails blocked.")

@admin.action(description="Delete user and block email and domain")
def block_email_and_domain(modeladmin, request, queryset):
    for user in queryset:
        domain = user.email.split("@")[-1]
        BlockedEmail.objects.create(email=user.email)  
        BlockedDomain.objects.get_or_create(domain=domain)  
        user.delete()
    modeladmin.message_user(request, "Selected users have been deleted and their emails/domains blocked.")
    
@admin.action(description="Regenerate GeoJSON & GeoPackage now")
def regenerate_all_exports(modeladmin, request, queryset):
    """
    Immediately rebuild both:
      • the /tmp/optimap_cache/geojson_cache.json
      • the /tmp/optimap_cache/publications.gpkg
    """
    try:
        regenerate_geojson_cache()
        regenerate_geopackage_cache()
        messages.success(request, "GeoJSON & GeoPackage caches were regenerated.")
    except Exception as e:
        messages.error(request, f"Error during export regeneration: {e}")
 
@admin.register(Publication)
class PublicationAdmin(LeafletGeoAdmin, ImportExportModelAdmin):
    list_display  = ("title", "doi", "has_permalink", "permalink_link",
                     "creationDate", "lastUpdate", "created_by", "updated_by",
                     "status", "provenance", "source", "openalex_id")
    search_fields = ("title", "doi", "abstract", "source__name", "openalex_id")
    list_filter   = ("status", "creationDate", "openalex_is_retracted", "openalex_open_access_status")
    fields        = ("title", "doi", "status", "source", "abstract",
                     "geometry", "timeperiod_startdate", "timeperiod_enddate",
                     "created_by", "updated_by", "provenance",
                     "authors", "keywords", "topics",
                     "openalex_id", "openalex_link", "openalex_match_info",
                     "openalex_fulltext_origin", "openalex_is_retracted",
                     "openalex_ids", "openalex_open_access_status")
    readonly_fields = ("created_by", "updated_by", "openalex_link")
    actions = [make_public, make_draft, regenerate_all_exports,
               "export_permalinks_csv", "email_permalinks_preview",
               export_to_wikidata, export_to_wikidata_dryrun]

    @admin.display(boolean=True, description="Has DOI")
    def has_permalink(self, obj):
        return bool(obj.doi)

    @admin.display(description="Permalink")
    def permalink_link(self, obj):
        url = obj.permalink()
        return format_html('<a href="{}" target="_blank">{}</a>', url, url) if url else "—"

    @admin.display(description="OpenAlex Link")
    def openalex_link(self, obj):
        if obj.openalex_id:
            return format_html('<a href="{}" target="_blank"><i class="fas fa-external-link-alt"></i> View in OpenAlex</a>', obj.openalex_id)
        return "—"

    def export_permalinks_csv(self, request, queryset):
        rows = [("title", "doi", "permalink")]
        rows += [(p.title or "", p.doi, p.permalink() or "")
                 for p in queryset.only("title", "doi") if p.doi]
        if len(rows) == 1:
            self.message_user(request, "No items with DOI in selection.", level=messages.WARNING)
            return
        #esc = lambda v: f"\"{(v or '').replace('\"','\"\"')}\""
        escape_row = lambda v: '"{}"'.format((v or '').replace('"', '""'))
        csv = "\n".join(",".join(map(escape_row, r)) for r in rows)
        resp = HttpResponse(csv, content_type="text/csv; charset=utf-8")
        resp["Content-Disposition"] = 'attachment; filename="publication_permalinks.csv"'
        return resp
    export_permalinks_csv.short_description = "Export permalinks (CSV)"

    def email_permalinks_preview(self, request, queryset):
        base = settings.BASE_URL.rstrip("/")
        c = Client()
        lines, ok, bad = [], 0, 0
        for p in queryset.only("title", "doi"):
            if not p.doi:
                continue
            url = p.permalink()
            path = url[len(base):] if url and url.startswith(base) else url
            status = c.get(path).status_code
            ok += (status == 200); bad += (status != 200)
            lines.append(f"{'✅' if status == 200 else '❌'} {p.title} — {url} (HTTP {status})")
        if not lines:
            self.message_user(request, "No items with DOI in selection.", level=messages.WARNING)
            return
        send_mail(
            "OPTIMAP — Permalink preview",
            "Selected publication permalinks:\n\n" + "\n".join(lines) + f"\n\nSummary: {ok} OK, {bad} not OK",
            settings.EMAIL_HOST_USER, [request.user.email]
        )
        self.message_user(request, f"Emailed preview to {request.user.email}.", level=messages.INFO)
    email_permalinks_preview.short_description = "Email permalinks preview to me"
    
@admin.register(HarvestingEvent)
class HarvestingEventAdmin(admin.ModelAdmin):
    list_display = ("id", "source", "status", "started_at", "completed_at")
    list_filter = ("status", "started_at", "completed_at")
    search_fields = ("source__url",)


@admin.register(EmailLog)
class EmailLogAdmin(admin.ModelAdmin):
    list_display = (
        "recipient_email",
        "subject",
        "sent_at",
        "sent_by",
        "trigger_source",
        "status",
        "error_message",
    )
    list_filter = ("status", "trigger_source", "sent_at")
    search_fields = ("recipient_email", "subject", "sent_by__username")
    actions = [trigger_monthly_email, trigger_monthly_email_task]

@admin.register(WikidataExportLog)
class WikidataExportLogAdmin(admin.ModelAdmin):
    """Admin interface for Wikidata export logs."""
    list_display = (
        "id",
        "publication_title",
        "action",
        "wikidata_link",
        "export_date",
        "fields_count",
    )
    list_filter = ("action", "export_date")
    search_fields = (
        "publication__title",
        "publication__doi",
        "wikidata_qid",
        "export_summary",
    )
    readonly_fields = (
        "publication",
        "export_date",
        "action",
        "wikidata_qid",
        "wikidata_url",
        "wikidata_link_display",
        "wikibase_endpoint",
        "exported_fields",
        "error_message_display",
        "export_summary",
    )
    fields = (
        "publication",
        "export_date",
        "action",
        "wikibase_endpoint",
        "wikidata_qid",
        "wikidata_link_display",
        "export_summary",
        "exported_fields",
        "error_message_display",
    )
    ordering = ("-export_date",)
    date_hierarchy = "export_date"

    @admin.display(description="Publication")
    def publication_title(self, obj):
        return obj.publication.title[:60] if obj.publication else "—"

    @admin.display(description="Wikidata")
    def wikidata_link(self, obj):
        if obj.wikidata_qid and obj.wikidata_url:
            return format_html(
                '<a href="{}" target="_blank" rel="noopener"><i class="fas fa-external-link-alt"></i> {}</a>',
                obj.wikidata_url,
                obj.wikidata_qid
            )
        return "—"

    @admin.display(description="Wikidata Link")
    def wikidata_link_display(self, obj):
        if obj.wikidata_qid and obj.wikidata_url:
            return format_html(
                '<a href="{}" target="_blank" rel="noopener">{}</a>',
                obj.wikidata_url,
                obj.wikidata_url
            )
        return "—"

    @admin.display(description="Fields")
    def fields_count(self, obj):
        if obj.exported_fields:
            return len(obj.exported_fields)
        return 0

    @admin.display(description="Error Message (Full Traceback)")
    def error_message_display(self, obj):
        if obj.error_message:
            return format_html(
                '<pre style="white-space: pre-wrap; font-family: monospace; font-size: 12px; background: #f5f5f5; padding: 10px; border: 1px solid #ddd; border-radius: 4px; max-height: 400px; overflow-y: auto;">{}</pre>',
                obj.error_message
            )
        return "—"

@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    list_display = ("user", "region", "subscribed")
    actions = [send_subscription_emails, send_subscription_emails_scheduler]

@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "notify_new_manuscripts")  
    search_fields = ("user__email",)

@admin.register(BlockedEmail)
class BlockedEmailAdmin(admin.ModelAdmin):
    list_display = ('email', 'created_at', 'blocked_by')
    search_fields = ('email',)

@admin.register(BlockedDomain)
class BlockedDomainAdmin(admin.ModelAdmin):
    list_display = ('domain', 'created_at', 'blocked_by')
    search_fields = ('domain',)

@admin.register(CustomUser)
class UserAdmin(admin.ModelAdmin):
    """User Admin."""
    list_display = ("username", "email", "is_active")
    actions = [block_email, block_email_and_domain]

@admin.register(GlobalRegion)
class GlobalRegionAdmin(admin.ModelAdmin):
    """GlobalRegion Admin."""

