# SPDX-FileCopyrightText: 2022 OPTIMETA and KOMET projects <https://projects.tib.eu/komet>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Django-Q task entry points.

The harvesting code lives in the ``works.harvesting`` package — one module
per source type (OAI-PMH / RSS / Crossref / MaRESS) plus shared helpers.
This module re-exports the public surface so existing dotted-path schedules
(``works.tasks.harvest_oai_endpoint`` etc.), test imports, and ``@patch``
targets keep resolving without migration.

The non-harvest tasks (monthly email digest, subscription emails, GeoJSON /
GeoPackage cache regeneration, schedule helpers) still live here.
"""

import calendar
import glob
import gzip
import json
import logging
import os
import subprocess
import tempfile
import time
from collections import defaultdict
from datetime import datetime, timedelta
from datetime import timezone as dt_timezone
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.mail import EmailMessage, send_mail
from django.core.serializers import serialize
from django.urls import reverse
from django.utils import timezone
from django_q.models import Schedule
from django_q.tasks import schedule

# -----------------------------------------------------------------------------
# Re-exports from the harvesting package — preserve the public surface that
# Django-Q schedule rows (`works.tasks.harvest_*`), tests, and admin actions
# reference by dotted path.
# -----------------------------------------------------------------------------
from works.harvesting.common import (  # noqa: F401
    HarvestStats,
    HarvestWarningCollector,
    _carefully_update_work,
    _find_existing_work,
    _get_article_link,
    _is_empty_for_update,
    _save_or_update_work,
    complete_harvest,
    fail_harvest,
    get_or_create_admin_command_user,
    parse_publication_date,
    resolve_user,
    send_harvest_email,
)
from works.harvesting.crossref import (  # noqa: F401
    CROSSREF_API_URL,
    CROSSREF_HTTP_TIMEOUT,
    CROSSREF_PAGE_ROWS,
    _build_crossref_filter,
    _crossref_item_to_work_kwargs,
    _crossref_session,
    _strip_jats,
    fetch_copernicus_abstract,
    harvest_crossref_book_list,
    harvest_crossref_prefix,
    parse_crossref_response_and_save_works,
)
from works.harvesting.geoscienceworld import (  # noqa: F401
    harvest_geoscienceworld,
    parse_gsw_response_and_save_works,
)
from works.harvesting.metadata_html import (  # noqa: F401
    _extract_dc_box,
    _extract_dc_spatial_coverage,
    _extract_dc_temporal,
    _extract_geojson_link,
    _extract_jsonld_spatial,
    _extract_jsonld_temporal,
    _geom_from_geojson_dict,
    _polygon_from_bbox,
    _split_iso_interval,
    _walk_jsonld,
    _wrap_in_collection,
    extract_geometry_from_html,
    extract_timeperiod_from_html,
)
from works.harvesting.mountain_wetlands import (  # noqa: F401
    MWR_HTTP_TIMEOUT,
    MWR_PAGE_SIZE,
    _mwr_authors_list,
    _mwr_first_author_surname,
    _mwr_geometry_from_study_sites,
    _mwr_item_url,
    _mwr_publication_year,
    _mwr_session,
    harvest_mountain_wetlands,
    parse_mountain_wetlands_response_and_save_works,
)
from works.harvesting.oai import (  # noqa: F401
    DOI_REGEX,
    harvest_oai_endpoint,
    parse_oai_xml_and_save_works,
)
from works.harvesting.openalex import build_openalex_fields  # noqa: F401
from works.harvesting.openalex_source import (  # noqa: F401
    OPENALEX_API_URL,
    OPENALEX_HTTP_TIMEOUT,
    OPENALEX_PAGE_SIZE,
    _openalex_session,
    harvest_openalex_source,
    parse_openalex_response_and_save_works,
)
from works.harvesting.rss import (  # noqa: F401
    harvest_rss_endpoint,
    parse_rss_feed_and_save_publications,
)
from works.harvesting.sessions import (  # noqa: F401
    OAI_HTTP_TIMEOUT,
    OAI_RETRY_TOTAL,
    OAI_USER_AGENT,
    _looks_like_oai_xml,
    _oai_session,
    _short_body,
)
from works.models import EmailLog, Subscription, Work
from works.utils.email import render_email

logger = logging.getLogger(__name__)
BASE_URL = settings.BASE_URL
CACHE_DIR = Path(tempfile.gettempdir()) / "optimap_cache"
User = get_user_model()


# -----------------------------------------------------------------------------
# Data-dump helpers (used by regenerate_geojson_cache / regenerate_geopackage_cache).
# -----------------------------------------------------------------------------


def generate_data_dump_filename(extension: str) -> str:
    ts = datetime.now(dt_timezone.utc).strftime("%Y%m%dT%H%M%S")
    return f"optimap_data_dump_{ts}.{extension}"


def cleanup_old_data_dumps(directory: Path, keep: int):
    """Keep the newest ``keep`` dump cycles, dropping older files.

    Each regen cycle now produces multiple files for the same timestamp
    (``optimap_data_dump_<ts>.geojson`` + ``.geojson.gz`` + ``.gpkg`` +
    ``.csv``). Counting raw files would prune fresh formats from the current
    cycle (e.g. drop ``.csv`` because it sorts after ``.gpkg``); instead, we
    group by the ``optimap_data_dump_<ts>`` prefix and keep the newest
    ``keep`` *cycles*.
    """
    pattern = str(directory / "optimap_data_dump_*")
    files = glob.glob(pattern)
    # Group by `optimap_data_dump_<TS>`. The timestamp is fixed-width
    # (``%Y%m%dT%H%M%S``) so the second underscore-delimited field is the
    # full prefix we want regardless of extension.
    cycles = defaultdict(list)
    for path in files:
        name = os.path.basename(path)
        # `optimap_data_dump_<TS>.<ext>` — split on the first '.' to get the
        # cycle key (drops the extension, including compound `.geojson.gz`).
        cycle_key = name.split(".", 1)[0]
        cycles[cycle_key].append(path)
    for cycle_key in sorted(cycles, reverse=True)[keep:]:
        for old in cycles[cycle_key]:
            try:
                os.remove(old)
            except OSError:
                logger.warning("Could not delete old dump %s", old)


# -----------------------------------------------------------------------------
# Monthly email digest.
# -----------------------------------------------------------------------------


def send_monthly_email(trigger_source="manual", sent_by=None):
    """
    Send the monthly digest of new manuscripts to users who opted in.

    Rules:
      - One email per distinct recipient with a non-empty address.
      - Link for each work:
          * if DOI present  -> prefer OPTIMAP permalink, fallback to https://doi.org/<doi>
          * else            -> fallback to Work.url (may be empty)
      - Log success/failure to EmailLog.
      - Respect settings.EMAIL_SEND_DELAY if present.
    """
    recipients_qs = (
        User.objects.filter(userprofile__notify_new_manuscripts=True)
        .exclude(email__isnull=True)
        .exclude(email__exact="")
        .values_list("email", flat=True)
        .distinct()
    )
    recipients = list(recipients_qs)

    last_month = timezone.now().replace(day=1) - timedelta(days=1)
    new_manuscripts = Work.objects.filter(
        creationDate__year=last_month.year,
        creationDate__month=last_month.month,
    )

    if not recipients or not new_manuscripts.exists():
        return

    def link_for(work):
        if work.doi:
            try:
                permalink = work.permalink()
            except TypeError:
                permalink = work.permalink if hasattr(work, "permalink") else None
            if permalink:
                return permalink
            return f"https://doi.org/{work.doi}"
        return work.url or ""

    manuscripts = [{"title": w.title, "link": link_for(w)} for w in new_manuscripts]
    subject, content = render_email("email/monthly_digest.en.txt", {"manuscripts": manuscripts})

    delay_seconds = getattr(settings, "EMAIL_SEND_DELAY", 0)

    for recipient in recipients:
        try:
            send_mail(
                subject,
                content,
                settings.EMAIL_HOST_USER,
                [recipient],
                fail_silently=False,
            )
            EmailLog.log_email(
                recipient,
                subject,
                content,
                sent_by=sent_by,
                trigger_source=trigger_source,
                status="success",
            )
            if delay_seconds:
                time.sleep(delay_seconds)
        except Exception as e:
            logger.error("Failed to send monthly email to %s: %s", recipient, e)
            EmailLog.log_email(
                recipient,
                subject,
                content,
                sent_by=sent_by,
                trigger_source=trigger_source,
                status="failed",
                error_message=str(e),
            )


def send_subscription_based_email(trigger_source="manual", sent_by=None, user_ids=None, interval=None):
    """
    Send subscription-based notifications grouped by region.

    Publications are grouped by the regions the user has subscribed to.
    Each region group includes a link to the region's landing page.

    ``interval`` — when given ('weekly' or 'monthly'), only processes subscriptions
    whose ``notification_interval`` matches. Pass ``None`` (the default, used for
    manual/admin runs) to process all active subscriptions regardless of their
    interval setting.

    Only publications added since ``subscription.last_notified`` are included.
    If ``last_notified`` is unset, a sensible fallback window is used (7 days for
    weekly, 31 days for monthly, 31 days when interval is None).
    ``last_notified`` is updated only after a successful send.
    """
    query = Subscription.objects.filter(subscribed=True, user__isnull=False).prefetch_related("regions")
    if user_ids:
        query = query.filter(user__id__in=user_ids)
    if interval is not None:
        query = query.filter(notification_interval=interval)

    fallback_days = 7 if interval == "weekly" else 31

    for subscription in query:
        user_email = subscription.user.email

        subscribed_regions = list(subscription.regions.all())
        if not subscribed_regions:
            logger.info(f"Skipping subscription for {user_email} - no regions selected")
            continue

        cutoff = (
            subscription.last_notified
            if subscription.last_notified
            else (timezone.now() - timedelta(days=fallback_days))
        )

        region_publications = defaultdict(list)
        total_publications = 0

        for region in subscribed_regions:
            prepared_geom = region.geom.prepared

            candidates = Work.objects.filter(
                status="p",
                geometry__isnull=False,
                geometry__bboverlaps=region.geom,
                creationDate__gte=cutoff,
            ).order_by("-creationDate")[:50]

            matching_pubs = [work for work in candidates if prepared_geom.intersects(work.geometry)]

            if matching_pubs:
                region_publications[region] = matching_pubs
                total_publications += len(matching_pubs)

        if total_publications == 0:
            logger.info(f"Skipping subscription for {user_email} - no new publications since {cutoff}")
            continue

        unsubscribe_all = f"{BASE_URL}{reverse('optimap:unsubscribe')}?all=true"
        manage_subscriptions = f"{BASE_URL}{reverse('optimap:subscriptions')}"

        region_groups = []
        for region in sorted(region_publications.keys(), key=lambda r: r.name):
            pubs = region_publications[region]
            region_url = f"{BASE_URL}{region.get_absolute_url()}"
            pub_items = [
                {
                    "title": (w.title[:100] + "..." if len(w.title) > 100 else w.title),
                    "link": _get_article_link(w),
                }
                for w in pubs[:10]
            ]
            region_groups.append(
                {
                    "name": region.name,
                    "region_type": region.get_region_type_display(),
                    "pub_count": len(pubs),
                    "region_url": region_url,
                    "pubs": pub_items,
                    "extra_count": max(0, len(pubs) - 10),
                }
            )

        subject, content = render_email(
            "email/subscription_regional.en.txt",
            {
                "total_publications": total_publications,
                "username": subscription.user.username,
                "region_groups": region_groups,
                "manage_subscriptions": manage_subscriptions,
                "unsubscribe_all": unsubscribe_all,
                "base_url": BASE_URL,
            },
        )

        try:
            email = EmailMessage(subject, content, settings.EMAIL_HOST_USER, [user_email])
            email.send()
            EmailLog.log_email(
                user_email, subject, content, sent_by=sent_by, trigger_source=trigger_source, status="success"
            )
            logger.info(
                f"Sent regional subscription email to {user_email} with {total_publications} publications across {len(region_publications)} regions"
            )
            subscription.last_notified = timezone.now()
            subscription.save(update_fields=["last_notified"])
            time.sleep(settings.EMAIL_SEND_DELAY)
        except Exception as e:
            error_message = str(e)
            logger.error(f"Failed to send subscription email to {user_email}: {error_message}")
            EmailLog.log_email(
                user_email,
                subject,
                content,
                sent_by=sent_by,
                trigger_source=trigger_source,
                status="failed",
                error_message=error_message,
            )


def schedule_monthly_email_task(sent_by=None):
    if not Schedule.objects.filter(func="publications.tasks.send_monthly_email").exists():
        now = datetime.now()
        last_day_of_month = calendar.monthrange(now.year, now.month)[1]
        next_run_date = now.replace(day=last_day_of_month, hour=23, minute=59)
        schedule(
            "publications.tasks.send_monthly_email",
            schedule_type="M",
            repeats=-1,
            next_run=next_run_date,
            kwargs={"trigger_source": "scheduled", "sent_by": sent_by.id if sent_by else None},
        )
        logger.info(f"Scheduled 'schedule_monthly_email_task' for {next_run_date}")


def schedule_subscription_email_task(sent_by=None):
    monthly_kwargs = {"trigger_source": "scheduled", "interval": "monthly", "sent_by": sent_by.id if sent_by else None}
    if not Schedule.objects.filter(
        func="publications.tasks.send_subscription_based_email", kwargs__contains='"interval": "monthly"'
    ).exists():
        now = datetime.now()
        last_day_of_month = calendar.monthrange(now.year, now.month)[1]
        next_run_date = now.replace(day=last_day_of_month, hour=23, minute=59)
        schedule(
            "publications.tasks.send_subscription_based_email",
            schedule_type="M",
            repeats=-1,
            next_run=next_run_date,
            kwargs=monthly_kwargs,
        )
        logger.info(f"Scheduled monthly 'send_subscription_based_email' for {next_run_date}")


def schedule_weekly_subscription_email_task(sent_by=None):
    weekly_kwargs = {"trigger_source": "scheduled", "interval": "weekly", "sent_by": sent_by.id if sent_by else None}
    if not Schedule.objects.filter(
        func="publications.tasks.send_subscription_based_email", kwargs__contains='"interval": "weekly"'
    ).exists():
        schedule(
            "publications.tasks.send_subscription_based_email",
            schedule_type="C",
            cron="0 2 * * 1",
            repeats=-1,
            kwargs=weekly_kwargs,
        )
        logger.info("Scheduled weekly 'send_subscription_based_email' (Monday 02:00 UTC)")


# -----------------------------------------------------------------------------
# Inactivity warning (#120) and deletion list (#121).
# -----------------------------------------------------------------------------


def _next_monday():
    """Return next Monday at 08:00 (always at least 1 day ahead)."""
    now = timezone.now()
    days_ahead = (7 - now.weekday()) % 7 or 7
    return (now + timedelta(days=days_ahead)).replace(hour=8, minute=0, second=0, microsecond=0)


def send_inactivity_warning_emails(trigger_source="scheduled"):
    """Email users in the 12-to-13-month inactivity window (#120)."""
    from django.contrib.auth import get_user_model

    from works.models import EmailLog
    from works.views.auth import is_email_blocked

    User = get_user_model()
    now = timezone.now()
    warning_cutoff = now - timedelta(days=settings.INACTIVITY_WARNING_DAYS)
    deletion_cutoff = now - timedelta(days=settings.INACTIVITY_DELETION_DAYS)

    users = User.objects.filter(
        is_active=True,
        last_login__lt=warning_cutoff,
        last_login__gte=deletion_cutoff,
    ).exclude(email="")

    login_url = settings.BASE_URL

    for user in users:
        if is_email_blocked(user.email):
            logger.info("Skipping blocked address %s for inactivity warning.", user.email)
            continue
        subject, body = render_email(
            "email/account_inactivity_warning.en.txt",
            {
                "email": user.email,
                "login_url": login_url,
            },
        )
        try:
            send_mail(subject, body, settings.EMAIL_HOST_USER, [user.email], fail_silently=False)
            EmailLog.log_email(user.email, subject, body, trigger_source=trigger_source, status="success")
        except Exception as ex:  # noqa: BLE001
            logger.exception("Failed to send inactivity warning to %s.", user.email)
            EmailLog.log_email(
                user.email, subject, body, trigger_source=trigger_source, status="failed", error_message=str(ex)
            )
        time.sleep(settings.EMAIL_SEND_DELAY)


def send_inactivity_deletion_list_to_admins(trigger_source="scheduled"):
    """Email admins a list of users inactive for 13+ months (#121)."""
    from django.contrib.auth import get_user_model

    from works.models import EmailLog

    User = get_user_model()
    now = timezone.now()
    deletion_cutoff = now - timedelta(days=settings.INACTIVITY_DELETION_DAYS)

    stale_users = list(
        User.objects.filter(is_active=True, last_login__lt=deletion_cutoff).exclude(email="").order_by("last_login")
    )
    if not stale_users:
        logger.info("send_inactivity_deletion_list_to_admins: no users pending deletion.")
        return

    admin_emails = list(User.objects.filter(is_staff=True).exclude(email="").values_list("email", flat=True))
    if not admin_emails:
        logger.warning("send_inactivity_deletion_list_to_admins: no admin emails configured.")
        return

    # Attach the date of the most recent successful warning email to each user.
    stale_emails = [u.email for u in stale_users]
    warning_log_by_email = {}
    for log in EmailLog.objects.filter(
        recipient_email__in=stale_emails, subject__icontains="account will be deleted", status="success"
    ).order_by("-sent_at"):
        warning_log_by_email.setdefault(log.recipient_email, log)
    for user in stale_users:
        user.warning_log = warning_log_by_email.get(user.email)

    admin_url = f"{settings.BASE_URL}{reverse('admin:works_customuser_changelist')}"
    subject, body = render_email(
        "email/account_deletion_pending.en.txt",
        {
            "count": len(stale_users),
            "users": stale_users,
            "admin_url": admin_url,
        },
    )
    for admin_email in admin_emails:
        try:
            send_mail(subject, body, settings.EMAIL_HOST_USER, [admin_email], fail_silently=False)
            EmailLog.log_email(admin_email, subject, body, trigger_source=trigger_source, status="success")
        except Exception as ex:  # noqa: BLE001
            logger.exception("Failed to send deletion list to admin %s.", admin_email)
            EmailLog.log_email(
                admin_email, subject, body, trigger_source=trigger_source, status="failed", error_message=str(ex)
            )
        time.sleep(settings.EMAIL_SEND_DELAY)


def schedule_inactivity_warning_task():
    if not Schedule.objects.filter(func="works.tasks.send_inactivity_warning_emails").exists():
        schedule("works.tasks.send_inactivity_warning_emails", schedule_type="W", repeats=-1, next_run=_next_monday())
        logger.info("Scheduled send_inactivity_warning_emails weekly.")


def schedule_inactivity_deletion_task():
    if not Schedule.objects.filter(func="works.tasks.send_inactivity_deletion_list_to_admins").exists():
        schedule(
            "works.tasks.send_inactivity_deletion_list_to_admins",
            schedule_type="W",
            repeats=-1,
            next_run=_next_monday(),
        )
        logger.info("Scheduled send_inactivity_deletion_list_to_admins weekly.")


# -----------------------------------------------------------------------------
# Data dump regeneration.
# -----------------------------------------------------------------------------


def _unwrap_geometry_collection(geom):
    """Unwrap a single-member GeometryCollection to its primitive type.

    Django's GeometryCollectionField always emits a GEOMETRYCOLLECTION wrapper,
    even for a single Point or Polygon.  GIS tools (QGIS, ArcGIS) cannot apply
    default symbology to GEOMETRYCOLLECTION layers, so we strip the wrapper here
    before writing any GeoJSON or GeoPackage export.
    """
    if geom is None or geom.get("type") != "GeometryCollection":
        return geom
    parts = [g for g in (geom.get("geometries") or []) if g is not None]
    if not parts:
        return None
    if len(parts) == 1:
        return parts[0]
    types = {g["type"] for g in parts}
    if len(types) == 1:
        base = types.pop()
        multi_map = {"Point": "MultiPoint", "LineString": "MultiLineString", "Polygon": "MultiPolygon"}
        if base in multi_map:
            return {"type": multi_map[base], "coordinates": [g["coordinates"] for g in parts]}
    return geom


_DUMP_FIELDS = [
    "title",
    "type",
    "doi",
    "url",
    "publicationDate",
    "abstract",
    "volume",
    "issue",
    "first_page",
    "last_page",
    "timeperiod_startdate",
    "timeperiod_enddate",
    "authors",
    "keywords",
    "topics",
    "bok_concepts",
    "placename",
    "country_code",
    "openalex_id",
    "openalex_open_access_status",
    "openalex_is_retracted",
]


def regenerate_geojson_cache():
    cache_dir = os.path.join(tempfile.gettempdir(), "optimap_cache")
    os.makedirs(cache_dir, exist_ok=True)

    json_filename = generate_data_dump_filename("geojson")
    json_path = os.path.join(cache_dir, json_filename)

    works_qs = Work.objects.filter(status="p").select_related("source").prefetch_related("collections")

    base_url = settings.BASE_URL.rstrip("/")
    extra = {
        w.pk: {
            "source_name": w.source.name if w.source else None,
            "source_url": f"{base_url}/api/v1/sources/{w.source.pk}/" if w.source else None,
            "collections": [c.identifier for c in w.collections.all()],
        }
        for w in works_qs
    }

    raw = serialize(
        "geojson",
        works_qs,
        geometry_field="geometry",
        srid=4326,
        fields=_DUMP_FIELDS,
    )
    data = json.loads(raw)
    for feat in data.get("features", []):
        info = extra.get(feat.get("id"), {})
        props = feat.setdefault("properties", {})
        props.update(info)
        feat["geometry"] = _unwrap_geometry_collection(feat.get("geometry"))
    with open(json_path, "w") as f:
        json.dump(data, f)

    gzip_filename = generate_data_dump_filename("geojson.gz")
    gzip_path = os.path.join(cache_dir, gzip_filename)
    with open(json_path, "rb") as fin, gzip.open(gzip_path, "wb") as fout:
        fout.writelines(fin)

    size = os.path.getsize(json_path)
    logger.info("Cached GeoJSON at %s (%d bytes), gzipped at %s", json_path, size, gzip_path)
    cleanup_old_data_dumps(Path(cache_dir), settings.DATA_DUMP_RETENTION)
    return json_path


def convert_geojson_via_ogr(geojson_path, *, fmt, ext, layer_creation_options=None):
    """Convert an existing GeoJSON dump to ``fmt`` via ``ogr2ogr``.

    ``fmt`` is the OGR driver name (e.g. ``"GPKG"``, ``"CSV"``); ``ext`` is the
    file extension used for the output dump filename (e.g. ``"gpkg"``,
    ``"csv"``); ``layer_creation_options`` is a list of ``KEY=VALUE`` strings
    passed via ``-lco``. Returns the output path or ``None`` if ogr2ogr fails.
    """
    cache_dir = os.path.dirname(geojson_path)
    out_filename = generate_data_dump_filename(ext)
    out_path = os.path.join(cache_dir, out_filename)
    cmd = ["ogr2ogr", "-f", fmt, out_path, geojson_path]
    for opt in layer_creation_options or []:
        cmd.extend(["-lco", opt])
    try:
        output = subprocess.check_output(cmd, stderr=subprocess.STDOUT, text=True)
        logger.info("ogr2ogr output (%s):\n%s", fmt, output)
        return out_path
    except subprocess.CalledProcessError as err:
        logger.warning("ogr2ogr %s conversion failed: %s", fmt, err.output)
        return None


def convert_geojson_to_geopackage(geojson_path):
    return convert_geojson_via_ogr(geojson_path, fmt="GPKG", ext="gpkg")


def convert_geojson_to_csv(geojson_path):
    # `GEOMETRY=AS_WKT` makes ogr2ogr emit a `WKT` column instead of dropping
    # the geometry — that's the whole point of a CSV export for #206.
    return convert_geojson_via_ogr(
        geojson_path,
        fmt="CSV",
        ext="csv",
        layer_creation_options=["GEOMETRY=AS_WKT"],
    )


def regenerate_geopackage_cache():
    geojson_path = regenerate_geojson_cache()
    cache_dir = Path(geojson_path).parent
    gpkg_path = convert_geojson_to_geopackage(geojson_path)
    cleanup_old_data_dumps(cache_dir, settings.DATA_DUMP_RETENTION)
    return gpkg_path


def regenerate_csv_cache():
    geojson_path = regenerate_geojson_cache()
    cache_dir = Path(geojson_path).parent
    csv_path = convert_geojson_to_csv(geojson_path)
    cleanup_old_data_dumps(cache_dir, settings.DATA_DUMP_RETENTION)
    return csv_path


def regenerate_all_data_dumps():
    """Regenerate GeoJSON + GeoPackage + CSV from a single PostGIS pass.

    Used as the scheduled task (every ``DATA_DUMP_INTERVAL_HOURS`` hours) and
    by the admin "regenerate all data exports now" action. Returns a dict of
    ``{format: path}``; values may be ``None`` if a conversion failed (the
    GeoJSON path is always present — we'd have raised before this point).
    """
    geojson_path = regenerate_geojson_cache()
    cache_dir = Path(geojson_path).parent
    gpkg_path = convert_geojson_to_geopackage(geojson_path)
    csv_path = convert_geojson_to_csv(geojson_path)
    cleanup_old_data_dumps(cache_dir, settings.DATA_DUMP_RETENTION)
    return {"geojson": geojson_path, "gpkg": gpkg_path, "csv": csv_path}
