import logging
from django.apps import AppConfig
from django.db.models.signals import post_migrate
from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)

def schedule_data_dump(sender, **kwargs):
    from django_q.models import Schedule
    from django_q.tasks  import schedule

    func_name = "works.tasks.regenerate_geopackage_cache"
    if not Schedule.objects.filter(func=func_name).exists():
        schedule(
            func_name,
            schedule_type="I",
            minutes=settings.DATA_DUMP_INTERVAL_HOURS * 60,
            next_run=timezone.now(),
            repeats=-1,
        )
        logger.info(
            "Scheduled data‐dump task '%s' every %d hours",
            func_name,
            settings.DATA_DUMP_INTERVAL_HOURS,
        )

class WorksConfig(AppConfig):
    name               = "works"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        import works.signals
        post_migrate.connect(
            schedule_data_dump,
            sender=self,
            weak=False,
            dispatch_uid="works.schedule_data_dump",
        )
