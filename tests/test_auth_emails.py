# SPDX-FileCopyrightText: 2026 OPTIMETA and KOMET projects <https://projects.tib.eu/komet>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Content assertions for auth-flow emails (magic link, email change, account deletion).

These emails had no body-content assertions before the template migration —
only redirect/status checks existed. The tests here ensure that moving the
text to template files doesn't silently break the email content.
"""

from django.contrib.auth import get_user_model
from django.core import mail
from django.core.cache import cache
from django.test import Client, TestCase, override_settings
from django.urls import reverse

User = get_user_model()

EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"


@override_settings(EMAIL_BACKEND=EMAIL_BACKEND, EMAIL_HOST_USER="noreply@optimap.test")
class MagicLinkEmailContentTests(TestCase):
    def setUp(self):
        self.client = Client(SERVER_NAME="testserver")

    def test_magic_link_email_contains_link_and_validity(self):
        """Magic-link email body contains the token URL and the validity period."""
        mail.outbox = []
        response = self.client.post(reverse("optimap:login_response"), {"email": "user@example.com"})  # noqa: F841
        # The view redirects on success (may render error.html if SMTP fails — we use locmem).
        self.assertEqual(len(mail.outbox), 1)
        email = mail.outbox[0]
        self.assertIn("user@example.com", email.to)
        self.assertIn("/login/", email.body)       # token URL
        self.assertIn("10", email.body)            # validity period in minutes
        self.assertIn("user@example.com", email.body)


@override_settings(
    EMAIL_BACKEND=EMAIL_BACKEND,
    EMAIL_HOST_USER="noreply@optimap.test",
    BASE_URL="http://testserver",
)
class EmailChangeEmailContentTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username="old@example.com", email="old@example.com", password="pass"
        )
        self.client.force_login(self.user)

    def test_confirmation_email_contains_old_and_new_address_and_link(self):
        """Email-change confirmation email contains both addresses and the confirm URL."""
        mail.outbox = []
        self.client.post(
            reverse("optimap:changeuser"),
            {"form": "email", "email_new": "new@example.com"},
        )
        # One email sent to the new address.
        self.assertEqual(len(mail.outbox), 1)
        email = mail.outbox[0]
        self.assertEqual(email.to, ["new@example.com"])
        self.assertIn("old@example.com", email.body)
        self.assertIn("new@example.com", email.body)
        self.assertIn("/confirm-email/", email.body)
        self.assertIn("10", email.body)            # expiry in minutes

    def test_notification_email_sent_to_old_address_after_confirmation(self):
        """After confirming an email change, the old address receives a security notice."""
        # Key format: EMAIL_CONFIRMATION_TOKEN_PREFIX + "_" + email_new = "email_confirmation__new@..."
        cache.set("email_confirmation__new@example.com", {
            "token": "testtoken123",
            "old_email": "old@example.com",
        }, timeout=600)
        mail.outbox = []
        self.client.get(
            reverse("optimap:confirm_email_change", args=["testtoken123", "new@example.com"])
        )
        # Exactly one email is expected — the security notice to the old address.
        self.assertEqual(len(mail.outbox), 1, "Expected one security-notice email")
        notify = mail.outbox[0]
        self.assertIn("old@example.com", notify.to)
        self.assertIn("old@example.com", notify.body)
        self.assertIn("new@example.com", notify.body)
        self.assertIn("contact", notify.body.lower())
