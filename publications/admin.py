from django.contrib import admin, messages
from leaflet.admin import LeafletGeoAdmin
from publications.models import Publication
from import_export.admin import ImportExportModelAdmin
from django_q.tasks import schedule
from django.utils.timezone import now
from publications.models import EmailLog, UserProfile
from publications.tasks import send_monthly_email, schedule_monthly_email_task
from django_q.models import Schedule
from datetime import datetime, timedelta


@admin.action(description="Mark selected publications as published")
def make_public(modeladmin, request, queryset):
    queryset.update(status="p")

@admin.action(description="Mark selected publications as draft (unpublished)")
def make_draft(modeladmin, request, queryset):
    queryset.update(status="d")

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

@admin.register(Publication)
class PublicationAdmin(LeafletGeoAdmin, ImportExportModelAdmin):
    """Publication Admin."""

    list_display = ("doi", "creationDate", "lastUpdate", "created_by", "updated_by", "status", "provenance")

    actions = [make_public,make_draft]

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


class UserProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "notify_new_manuscripts")  
    search_fields = ("user__email",)


admin.site.register(EmailLog, EmailLogAdmin)
admin.site.register(UserProfile, UserProfileAdmin)
