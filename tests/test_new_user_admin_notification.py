# SPDX-FileCopyrightText: 2026 OPTIMETA and KOMET projects <https://projects.tib.eu/komet>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests for admin email notification on first-time confirmed user registration.

Covers ``works.notifications.notify_admins_new_user_registered`` plus its wiring
inside ``authenticate_via_magic_link`` (only fresh accounts persisted via the
``?confirmed=true`` magic-link branch trigger the email).
"""

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core import mail
from django.core.cache import cache
from django.test import TestCase, Client, override_settings
from django.urls import reverse

from works.models import EmailLog

User = get_user_model()


def _run_async_synchronously(*args, **kwargs):
    """Replacement for ``django_q.tasks.async_task`` — invokes the dotted-path
    function in-process so tests don't need a running cluster."""
    func_path = args[0]
    module_name, _, attr = func_path.rpartition(".")
    from importlib import import_module
    module = import_module(module_name)
    fn = getattr(module, attr)
    return fn(*args[1:], **kwargs)


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    EMAIL_HOST_USER="optimap@example.org",
    BASE_URL="http://testserver",
)
class NewUserAdminNotificationTests(TestCase):
    """The magic-link view emails admins on first confirmed login."""

    def setUp(self):
        self.client = Client()
        self.admin1 = User.objects.create_user(
            username="admin1", email="admin1@optimap.example", password="x", is_staff=True,
        )
        self.admin2 = User.objects.create_user(
            username="admin2", email="admin2@optimap.example", password="x", is_staff=True,
        )
        # Sanity: a non-staff user already in the system should not receive notification.
        self.other = User.objects.create_user(
            username="other", email="other@example.org", password="x",
        )
        mail.outbox = []

    def _prime_magic_link(self, email: str, token: str = "tok-new"):
        cache.set(token, {"email": email, "next": "/"}, timeout=600)
        return token

    def test_first_confirmed_login_notifies_all_admins(self):
        token = self._prime_magic_link("brand-new@example.org")

        with patch("django_q.tasks.async_task", side_effect=_run_async_synchronously):
            response = self.client.get(
                reverse("optimap:magic_link", args=[token]) + "?confirmed=true"
            )

        self.assertEqual(response.status_code, 302)
        self.assertTrue(User.objects.filter(email="brand-new@example.org").exists())

        recipients = sorted(addr for m in mail.outbox for addr in m.to)
        self.assertEqual(len(mail.outbox), 2)
        self.assertEqual(
            recipients, ["admin1@optimap.example", "admin2@optimap.example"]
        )
        subject = mail.outbox[0].subject
        self.assertIn("new user registered", subject)
        self.assertIn("brand-new@example.org", subject)
        # Body carries the admin user page link.
        body = mail.outbox[0].body
        self.assertIn("brand-new@example.org", body)
        self.assertIn("/admin/works/customuser/", body)

        # EmailLog rows recorded.
        logs = EmailLog.objects.filter(subject__contains="new user registered")
        self.assertEqual(logs.count(), 2)
        self.assertTrue(all(log.status == "success" for log in logs))

    def test_existing_user_login_does_not_notify(self):
        """Returning users skip the create_user branch and must not trigger the email."""
        existing = User.objects.create_user(
            username="returning@example.org", email="returning@example.org",
        )
        token = self._prime_magic_link(existing.email, token="tok-returning")

        with patch("django_q.tasks.async_task", side_effect=_run_async_synchronously):
            response = self.client.get(reverse("optimap:magic_link", args=[token]))

        self.assertEqual(response.status_code, 302)
        self.assertEqual(len(mail.outbox), 0)
        self.assertFalse(
            EmailLog.objects.filter(subject__contains="new user registered").exists()
        )

    def test_unconfirmed_first_visit_does_not_notify(self):
        """First leg of the new-account flow (no ?confirmed=true) renders the
        confirmation page and must not create the user or notify admins."""
        token = self._prime_magic_link("pending@example.org", token="tok-pending")

        with patch("django_q.tasks.async_task", side_effect=_run_async_synchronously):
            response = self.client.get(reverse("optimap:magic_link", args=[token]))

        self.assertEqual(response.status_code, 200)
        self.assertFalse(User.objects.filter(email="pending@example.org").exists())
        self.assertEqual(len(mail.outbox), 0)

    def test_no_admins_no_error(self):
        """If no staff users exist, the notification is a no-op (login succeeds)."""
        User.objects.filter(is_staff=True).delete()
        token = self._prime_magic_link("loneranger@example.org")

        with patch("django_q.tasks.async_task", side_effect=_run_async_synchronously):
            response = self.client.get(
                reverse("optimap:magic_link", args=[token]) + "?confirmed=true"
            )

        self.assertEqual(response.status_code, 302)
        self.assertTrue(User.objects.filter(email="loneranger@example.org").exists())
        self.assertEqual(len(mail.outbox), 0)

    def test_staff_with_empty_email_skipped(self):
        """A staff user with no email address must not appear as a recipient."""
        User.objects.create_user(
            username="silent-admin", email="", password="x", is_staff=True,
        )
        token = self._prime_magic_link("freshie@example.org")

        with patch("django_q.tasks.async_task", side_effect=_run_async_synchronously):
            self.client.get(
                reverse("optimap:magic_link", args=[token]) + "?confirmed=true"
            )

        recipients = sorted(addr for m in mail.outbox for addr in m.to)
        self.assertNotIn("", recipients)
        self.assertEqual(len(mail.outbox), 2)  # admin1 + admin2 only

    def test_notification_failure_does_not_block_login(self):
        """If async_task raises, the user must still be created and logged in
        (notify_* is wrapped in defensive try/except)."""
        token = self._prime_magic_link("resilient@example.org")

        with patch(
            "django_q.tasks.async_task",
            side_effect=RuntimeError("queue offline"),
        ):
            response = self.client.get(
                reverse("optimap:magic_link", args=[token]) + "?confirmed=true"
            )

        self.assertEqual(response.status_code, 302)
        self.assertTrue(User.objects.filter(email="resilient@example.org").exists())
