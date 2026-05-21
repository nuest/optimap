# SPDX-FileCopyrightText: 2026 OPTIMETA and KOMET projects <https://projects.tib.eu/komet>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Admin-routed email notifications.

``Work`` state changes (today: ``contribution`` and ``publish``) dispatch via
``notify_work_event(work, event_type, actor=user)`` after ``work.save()``; add a
third by writing a private ``_enqueue_<event>`` function and adding it to
``WORK_EVENT_HANDLERS``.

User-lifecycle events dispatch separately — see
``notify_admins_new_user_registered(user)`` further down, called from the
magic-link view when a brand-new account is persisted for the first time.

Email sending happens inside Django-Q tasks (``send_*`` below) so the request
that triggered the state change stays fast. Recipient resolution stays in the
caller's transaction so the queue payload is a stable list of user IDs.

Recipient transparency: each contribution-review email body lists the *roles +
counts* of who else got the notification (e.g. "1 admin and 2 curators of
'Mountain Wetlands'") so a curator who picks up the work knows others may act
on it concurrently. Individual emails are not leaked between recipients.
"""

from __future__ import annotations

import logging
from typing import Iterable

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.mail import send_mail
from django.urls import reverse
from django.utils import timezone

logger = logging.getLogger(__name__)
User = get_user_model()


# ---------------------------------------------------------------------------
# Public dispatch
# ---------------------------------------------------------------------------

def notify_work_event(work, event_type: str, actor=None) -> None:
    """Queue notifications for a ``Work`` state change.

    No-op (with a debug log) when ``event_type`` has no registered handler, so
    callers can sprinkle this on every state transition without fear.
    """
    handler = WORK_EVENT_HANDLERS.get(event_type)
    if not handler:
        logger.debug("No notification handler for work event %r — skipping.", event_type)
        return
    try:
        handler(work, actor)
    except Exception:  # noqa: BLE001 — notification must never crash the state change
        logger.exception(
            "notify_work_event(%r) failed for work id=%s; state change is unaffected.",
            event_type, getattr(work, "pk", None),
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _absolute_work_url(work) -> str:
    """Absolute URL to the public work landing page."""
    return f"{settings.BASE_URL}{reverse('optimap:work-landing', args=[work.get_identifier()])}"


def _opted_in(qs):
    """Filter a User queryset to those who haven't opted out of work-event emails.

    Uses ``exclude(...=False)`` rather than ``filter(...=True)`` so that any
    user without a ``UserProfile`` row (legacy / fixture-loaded accounts that
    bypass the ``post_save`` signal) is treated as opted-in by default — the
    field is opt-out per the docstring on ``UserProfile.notify_work_events``.
    """
    return qs.exclude(userprofile__notify_work_events=False)


def _curators_for_work(work):
    """Return a queryset of curator users for any collection that contains ``work``."""
    return _opted_in(User.objects.filter(
        curated_collections__in=work.collections.all(),
        email__gt="",
    ).distinct())


def _admins():
    """Return a queryset of staff users with an email address."""
    return _opted_in(User.objects.filter(is_staff=True).exclude(email__exact="").distinct())


def _format_role_summary(admins_count: int, curator_collections: list[str]) -> str:
    """Roles + counts for the recipient-transparency block.

    >>> _format_role_summary(1, ["Mountain Wetlands"])
    "1 admin and 1 curator of 'Mountain Wetlands'"
    >>> _format_role_summary(2, ["A", "B"])
    "2 admins and 2 curators of 'A', 'B'"
    """
    parts = []
    if admins_count:
        parts.append(f"{admins_count} admin" + ("s" if admins_count != 1 else ""))
    if curator_collections:
        n = len(curator_collections)
        names = ", ".join(f"'{c}'" for c in curator_collections)
        parts.append(f"{n} curator" + ("s" if n != 1 else "") + f" of {names}")
    if not parts:
        return "0 recipients"
    if len(parts) == 1:
        return parts[0]
    return " and ".join(parts)


# ---------------------------------------------------------------------------
# Contribution review notification — admins + curators
# ---------------------------------------------------------------------------

def _enqueue_contribution_review(work, actor) -> None:
    from django_q.tasks import async_task  # local import to keep test isolation simple

    admin_ids = list(_admins().exclude(pk=getattr(actor, "pk", None)).values_list("id", flat=True))
    curator_ids_by_collection = {}
    for collection in work.collections.all():
        ids = list(
            _opted_in(collection.curators.filter(email__gt=""))
            .exclude(pk=getattr(actor, "pk", None))
            .values_list("id", flat=True)
        )
        if ids:
            curator_ids_by_collection[collection.name] = ids

    # Distinct recipient set across all roles, plus the role label per user
    # (deduplicated: an admin who also happens to curate a collection is
    # listed once with the "admin" role to avoid double-emailing).
    all_curator_ids = {uid for ids in curator_ids_by_collection.values() for uid in ids}
    distinct_recipient_ids = set(admin_ids) | all_curator_ids
    if not distinct_recipient_ids:
        logger.info("Contribution to work id=%s — no admin or curator recipients.", work.pk)
        return

    role_summary = _format_role_summary(
        admins_count=len(admin_ids),
        curator_collections=sorted(curator_ids_by_collection.keys()),
    )

    async_task(
        "works.notifications.send_contribution_review_email",
        list(distinct_recipient_ids),
        work.pk,
        getattr(actor, "pk", None),
        role_summary,
    )


def send_contribution_review_email(
    recipient_ids: Iterable[int],
    work_id: int,
    actor_id: int | None,
    role_summary: str,
) -> None:
    """Django-Q task: notify admins + curators of a new contribution."""
    from works.models import Work  # local: avoid circular import on app boot

    try:
        work = Work.objects.get(pk=work_id)
    except Work.DoesNotExist:
        logger.warning("send_contribution_review_email: work id=%s vanished.", work_id)
        return

    actor = User.objects.filter(pk=actor_id).first() if actor_id else None
    actor_label = actor.email if actor and actor.email else (actor.username if actor else "(unknown)")

    subject = f"OPTIMAP: contribution to review — {work.title[:120]}"
    body = (
        f"{actor_label} just contributed metadata to a work in OPTIMAP.\n\n"
        f"Title: {work.title}\n"
        f"DOI: {work.doi or '(none)'}\n"
        f"Submitted at: {timezone.now().isoformat(timespec='seconds')}\n\n"
        f"Open the work page to review:\n"
        f"  {_absolute_work_url(work)}\n\n"
        f"This notification was sent to: {role_summary}.\n"
        f"Any of the listed admins or curators can publish the work, so by the time you "
        f"open the link the contribution may already have been reviewed.\n"
    )

    recipients = list(
        User.objects.filter(pk__in=list(recipient_ids))
        .exclude(email__exact="")
        .values_list("email", flat=True)
    )
    for email in recipients:
        try:
            send_mail(subject, body, settings.EMAIL_HOST_USER, [email], fail_silently=False)
        except Exception:  # noqa: BLE001
            logger.exception("Failed to send contribution-review email to %s.", email)


# ---------------------------------------------------------------------------
# Publication notification — original contributors
# ---------------------------------------------------------------------------

def _enqueue_publication_to_contributors(work, actor) -> None:
    from django_q.tasks import async_task

    # Suppress double-notification on republish cycles.
    provenance = work.provenance if isinstance(work.provenance, dict) else {}
    if provenance.get("publication_notified_at"):
        logger.debug(
            "Work id=%s already notified on a previous publish — skipping.", work.pk,
        )
        return

    from works.models import Contribution
    contributor_ids = list(
        Contribution.objects.filter(work=work)
        .exclude(user__pk=getattr(actor, "pk", None))
        # Honour the per-user opt-out — same exclude-False pattern as
        # ``_opted_in`` so users without a UserProfile row stay opted-in by
        # default (the field defaults to True at create time).
        .exclude(user__userprofile__notify_work_events=False)
        .values_list("user_id", flat=True)
        .distinct()
    )
    if not contributor_ids:
        return

    async_task(
        "works.notifications.send_publication_to_contributor_emails",
        contributor_ids,
        work.pk,
    )


def send_publication_to_contributor_emails(contributor_ids: Iterable[int], work_id: int) -> None:
    """Django-Q task: notify original contributors that a work has been published."""
    from works.models import Work, Contribution

    try:
        work = Work.objects.get(pk=work_id)
    except Work.DoesNotExist:
        logger.warning("send_publication_to_contributor_emails: work id=%s vanished.", work_id)
        return

    subject = f"OPTIMAP: a work you contributed to has been published — {work.title[:120]}"
    work_url = _absolute_work_url(work)

    for contributor_id in contributor_ids:
        contributor = User.objects.filter(pk=contributor_id).exclude(email__exact="").first()
        if not contributor:
            continue
        # Per-contributor body so we can list the specific contribution kinds.
        kinds = list(
            Contribution.objects.filter(work=work, user=contributor)
            .values_list("kind", flat=True)
            .distinct()
        )
        kind_label = ", ".join(sorted(kinds)) if kinds else "metadata"
        body = (
            f"Thank you! A work you contributed to has just been published.\n\n"
            f"Title: {work.title}\n"
            f"DOI: {work.doi or '(none)'}\n"
            f"Your contribution: {kind_label}\n\n"
            f"Open the public landing page:\n"
            f"  {work_url}\n\n"
            f"(Sent only to you.)\n"
        )
        try:
            send_mail(subject, body, settings.EMAIL_HOST_USER, [contributor.email], fail_silently=False)
        except Exception:  # noqa: BLE001
            logger.exception(
                "Failed to send publication notification to contributor %s.", contributor.email,
            )

    # Stamp the suppression marker after the fan-out so a republish cycle
    # does not re-notify. We use update() to avoid bumping lastUpdate /
    # re-running pre_save signals.
    new_provenance = dict(work.provenance) if isinstance(work.provenance, dict) else {}
    new_provenance["publication_notified_at"] = timezone.now().isoformat(timespec="seconds")
    Work.objects.filter(pk=work.pk).update(provenance=new_provenance)


# ---------------------------------------------------------------------------
# User lifecycle — admins on first confirmed login (new account persisted).
# ---------------------------------------------------------------------------

def notify_admins_new_user_registered(user) -> None:
    """Queue an admin notification for a freshly persisted user account.

    Called from ``authenticate_via_magic_link`` immediately after
    ``User.objects.create_user(...)``. A new ``CustomUser`` row is *only*
    created when a magic-link recipient clicks the "confirm" step of the
    two-step new-account flow, so reaching this code path is by construction
    a first-time confirmed registration — no separate "first login" check is
    needed.

    Failures must never break the login. Same defensive ``except Exception``
    wrapper as ``notify_work_event``.
    """
    try:
        from django_q.tasks import async_task

        admin_ids = list(
            User.objects.filter(is_staff=True)
            .exclude(email__exact="")
            .exclude(pk=getattr(user, "pk", None))  # the new user *could* be staff, e.g. a fixture seed
            .values_list("id", flat=True)
            .distinct()
        )
        if not admin_ids:
            logger.info(
                "New user %s registered — no staff recipients to notify.",
                getattr(user, "email", "(unknown)"),
            )
            return
        async_task(
            "works.notifications.send_new_user_admin_email",
            admin_ids,
            user.pk,
        )
    except Exception:  # noqa: BLE001 — notification must never crash login
        logger.exception(
            "notify_admins_new_user_registered failed for user id=%s; "
            "login is unaffected.", getattr(user, "pk", None),
        )


def send_new_user_admin_email(recipient_ids: Iterable[int], user_id: int) -> None:
    """Django-Q task: tell each admin that a new user just confirmed registration.

    Bypasses ``notify_work_events`` — the per-user flag is opt-out for *work*
    events; user-management notifications go to every staff member with an
    email address.
    """
    from works.models import EmailLog

    try:
        user = User.objects.get(pk=user_id)
    except User.DoesNotExist:
        logger.warning(
            "send_new_user_admin_email: user id=%s vanished before send.", user_id,
        )
        return

    user_admin_url = (
        f"{settings.BASE_URL}{reverse('admin:works_customuser_change', args=[user.pk])}"
    )
    subject = f"OPTIMAP: new user registered — {user.email}"
    body = (
        f"A new user just confirmed their first login on OPTIMAP.\n\n"
        f"Email: {user.email}\n"
        f"Username: {user.username}\n"
        f"Registered at: {user.date_joined.isoformat(timespec='seconds')}\n\n"
        f"Open the admin user page to review:\n"
        f"  {user_admin_url}\n\n"
        f"(Sent to all staff users.)\n"
    )

    admin_emails = list(
        User.objects.filter(pk__in=list(recipient_ids))
        .exclude(email__exact="")
        .values_list("email", flat=True)
    )
    for admin_email in admin_emails:
        try:
            send_mail(subject, body, settings.EMAIL_HOST_USER, [admin_email], fail_silently=False)
            EmailLog.log_email(
                recipient=admin_email,
                subject=subject,
                content=body,
                trigger_source="scheduled",
                status="success",
            )
        except Exception as ex:  # noqa: BLE001
            logger.exception("Failed to send new-user admin email to %s.", admin_email)
            EmailLog.log_email(
                recipient=admin_email,
                subject=subject,
                content=body,
                trigger_source="scheduled",
                status="failed",
                error_message=str(ex),
            )


# ---------------------------------------------------------------------------
# Registry — extend by adding entries here.
# ---------------------------------------------------------------------------

WORK_EVENT_HANDLERS = {
    "contribution": _enqueue_contribution_review,
    "publish":      _enqueue_publication_to_contributors,
    # Future:
    # "unpublish":  _enqueue_unpublish_audit,
}
