# SPDX-FileCopyrightText: 2026 OPTIMETA and KOMET projects <https://projects.tib.eu/komet>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests for inactivity warning emails (#120) and admin deletion list (#121)."""

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase, override_settings
from django.utils import timezone

from works.models import BlockedEmail, CustomUser, EmailLog
from works.tasks import send_inactivity_deletion_list_to_admins, send_inactivity_warning_emails

User = get_user_model()

_SETTINGS = dict(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    EMAIL_HOST_USER="optimap@example.org",
    BASE_URL="http://testserver",
    EMAIL_SEND_DELAY=0,
    INACTIVITY_WARNING_DAYS=365,
    INACTIVITY_DELETION_DAYS=396,
    ADMINS=[],  # suppress AdminEmailHandler noise in mail.outbox
)


def _make_user(username, email, last_login_days_ago=None, is_staff=False, is_active=True):
    u = User.objects.create_user(username=username, email=email, is_staff=is_staff, is_active=is_active)
    if last_login_days_ago is not None:
        u.last_login = timezone.now() - timedelta(days=last_login_days_ago)
        u.save(update_fields=["last_login"])
    return u


def _make_sentinel():
    sentinel, _ = CustomUser.objects.get_or_create(
        username="deleted",
        defaults={"email": "", "is_active": False, "is_staff": False},
    )
    return sentinel


@override_settings(**_SETTINGS)
class InactivityWarningTests(TestCase):
    """#120 — send_inactivity_warning_emails targets the 12-to-13-month window."""

    def setUp(self):
        _make_sentinel()
        mail.outbox = []

    def test_user_in_warning_window_gets_email(self):
        u = _make_user("old", "old@example.com", last_login_days_ago=380)
        send_inactivity_warning_emails()
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, [u.email])
        self.assertIn("deleted", mail.outbox[0].body.lower())
        self.assertIn("log in", mail.outbox[0].body.lower())

    def test_login_url_in_body(self):
        _make_user("old2", "old2@example.com", last_login_days_ago=370)
        send_inactivity_warning_emails()
        self.assertIn("testserver", mail.outbox[0].body)

    def test_recent_user_not_warned(self):
        _make_user("fresh", "fresh@example.com", last_login_days_ago=30)
        send_inactivity_warning_emails()
        self.assertEqual(len(mail.outbox), 0)

    def test_user_past_deletion_threshold_not_warned(self):
        # 14 months inactive — past the 13-month deletion window, should not get a warning
        _make_user("stale", "stale@example.com", last_login_days_ago=430)
        send_inactivity_warning_emails()
        self.assertEqual(len(mail.outbox), 0)

    def test_user_with_null_last_login_skipped(self):
        # last_login=None means never logged in — excluded by last_login__lt query
        _make_user("nologin", "nologin@example.com", last_login_days_ago=None)
        send_inactivity_warning_emails()
        self.assertEqual(len(mail.outbox), 0)

    def test_blocked_email_skipped(self):
        _make_user("blocked", "blocked@example.com", last_login_days_ago=380)
        BlockedEmail.objects.create(email="blocked@example.com")
        send_inactivity_warning_emails()
        self.assertEqual(len(mail.outbox), 0)
        self.assertFalse(EmailLog.objects.filter(recipient_email="blocked@example.com").exists())

    def test_email_log_recorded_on_success(self):
        _make_user("logged", "logged@example.com", last_login_days_ago=370)
        send_inactivity_warning_emails()
        log = EmailLog.objects.get(recipient_email="logged@example.com")
        self.assertEqual(log.status, "success")
        self.assertEqual(log.trigger_source, "scheduled")

    def test_inactive_user_not_warned(self):
        # is_active=False users are excluded
        _make_user("inactive", "inactive@example.com", last_login_days_ago=380, is_active=False)
        send_inactivity_warning_emails()
        self.assertEqual(len(mail.outbox), 0)

    def test_sentinel_not_warned(self):
        # The sentinel has is_active=False and email="" — must be excluded
        send_inactivity_warning_emails()
        self.assertEqual(len(mail.outbox), 0)


@override_settings(**_SETTINGS)
class InactivityDeletionListTests(TestCase):
    """#121 — send_inactivity_deletion_list_to_admins targets 13+ months inactive."""

    def setUp(self):
        _make_sentinel()
        self.admin = _make_user("admin", "admin@example.com", last_login_days_ago=10, is_staff=True)
        mail.outbox = []

    def test_no_stale_users_sends_no_email(self):
        send_inactivity_deletion_list_to_admins()
        self.assertEqual(len(mail.outbox), 0)

    def test_stale_user_listed_in_admin_email(self):
        stale = _make_user("olduser", "olduser@example.com", last_login_days_ago=430)
        send_inactivity_deletion_list_to_admins()
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, [self.admin.email])
        self.assertIn(stale.email, mail.outbox[0].body)

    def test_last_login_date_in_body(self):
        _make_user("olduser2", "old2@example.com", last_login_days_ago=400)
        send_inactivity_deletion_list_to_admins()
        self.assertRegex(mail.outbox[0].body, r"\d{4}-\d{2}-\d{2}")

    def test_warning_date_shown_when_log_exists(self):
        stale = _make_user("warned", "warned@example.com", last_login_days_ago=430)
        # Simulate a prior successful warning email in EmailLog.
        EmailLog.log_email(
            recipient=stale.email,
            subject="[OPTIMAP] ⚠️ Your OPTIMAP account will be deleted — please log in",
            content="body",
            trigger_source="scheduled",
            status="success",
        )
        send_inactivity_deletion_list_to_admins()
        body = mail.outbox[0].body
        self.assertIn("warned@example.com", body)
        self.assertIn("(success)", body)

    def test_no_warning_log_shows_none_on_record(self):
        _make_user("unwarned", "unwarned@example.com", last_login_days_ago=430)
        send_inactivity_deletion_list_to_admins()
        self.assertIn("none on record", mail.outbox[0].body)

    def test_multiple_admins_each_get_email(self):
        _make_user("olduser3", "old3@example.com", last_login_days_ago=430)
        admin2 = _make_user("admin2", "admin2@example.com", last_login_days_ago=5, is_staff=True)
        send_inactivity_deletion_list_to_admins()
        recipients = sorted(m.to[0] for m in mail.outbox)
        self.assertEqual(recipients, sorted([self.admin.email, admin2.email]))

    def test_no_admin_emails_no_crash(self):
        _make_user("olduser4", "old4@example.com", last_login_days_ago=430)
        User.objects.filter(is_staff=True).update(email="")
        send_inactivity_deletion_list_to_admins()
        self.assertEqual(len(mail.outbox), 0)

    def test_email_log_recorded_for_each_admin(self):
        _make_user("olduser5", "old5@example.com", last_login_days_ago=430)
        send_inactivity_deletion_list_to_admins()
        log = EmailLog.objects.get(recipient_email=self.admin.email)
        self.assertEqual(log.status, "success")
        self.assertEqual(log.trigger_source, "scheduled")

    def test_sentinel_not_listed(self):
        # Sentinel has is_active=False, email="" — must not appear in stale list
        send_inactivity_deletion_list_to_admins()
        # no stale users → no email at all
        self.assertEqual(len(mail.outbox), 0)

    def test_warning_window_user_not_in_deletion_list(self):
        # 12-13 months: warning window only, not yet deletion
        _make_user("warningonly", "warn@example.com", last_login_days_ago=380)
        send_inactivity_deletion_list_to_admins()
        self.assertEqual(len(mail.outbox), 0)


@override_settings(**_SETTINGS)
class SentinelAssignmentTests(TestCase):
    """Contributions are reassigned to the sentinel when a user is deleted."""

    def setUp(self):
        _make_sentinel()

    def test_contributions_reassigned_on_delete(self):
        from works.models import Contribution, Work

        user = _make_user("contrib", "contrib@example.com", last_login_days_ago=10)
        work = Work.objects.create(title="Test work", status="p")
        contrib = Contribution.objects.create(user=user, work=work, kind=Contribution.SPATIAL)

        user.delete()

        contrib.refresh_from_db()
        self.assertEqual(contrib.user, CustomUser.deleted_user())

    def test_sentinel_self_guard(self):
        # Deleting the sentinel itself should not error
        sentinel = CustomUser.deleted_user()
        # Sentinel should survive the pre_delete guard (it would skip reassignment)
        # We just verify the guard doesn't raise
        from works.signals import reassign_contributions_before_user_delete

        reassign_contributions_before_user_delete(sender=CustomUser, instance=sentinel)
