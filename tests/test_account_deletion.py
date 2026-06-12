# SPDX-FileCopyrightText: 2025 OPTIMETA and KOMET projects <https://projects.tib.eu/komet>
# SPDX-License-Identifier: GPL-3.0-or-later

import os
import django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "optimap.settings")
django.setup()
from django.core import mail
from django.test import TestCase, Client, override_settings
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.urls import reverse
import uuid
User = get_user_model()

class AccountDeletionTests(TestCase):
    def setUp(self):
        """Set up a test user and client"""
        self.client = Client()
        self.user = User.objects.create_user(username="testuser", email="test@example.com", password="password")
        self.client.login(username="testuser", password="password")
        self.delete_token = uuid.uuid4().hex
        cache.set(f"user_delete_token_{self.delete_token}", self.user.id, timeout=600)

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_request_delete_account(self):
        """Test that a user can request account deletion"""
        mail.outbox = []
        response = self.client.post(reverse("optimap:request_delete"))
        self.assertEqual(response.status_code, 302)
        self.assertIn("message=Check%20your%20email", response.url)

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_deletion_email_contains_confirmation_link(self):
        """Deletion confirmation email includes the token link and timeout."""
        mail.outbox = []
        self.client.post(reverse("optimap:request_delete"))
        self.assertEqual(len(mail.outbox), 1)
        email = mail.outbox[0]
        self.assertIn("deletion", email.subject.lower())
        self.assertIn("/confirm-delete/", email.body)
        self.assertIn("10", email.body)  # timeout_minutes

    def test_confirm_delete_account(self):
        """Test that a user can confirm account deletion"""
        response = self.client.get(reverse("optimap:confirm_delete", args=[self.delete_token]))
        self.assertEqual(response.status_code, 302)
        self.assertTrue(self.client.session.get("user_delete_token"))

    def test_finalize_delete_account(self):
        """Test that a user can finalize account deletion"""
        session = self.client.session
        session["user_delete_token"] = self.delete_token
        session.save()

        # Send delete request
        response = self.client.post(reverse("optimap:finalize_delete"))

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("optimap:main"))

        # User is removed from the database
        user = User.objects.filter(id=self.user.id).first()
        self.assertIsNone(user)

        # User is logged out — session must carry no auth identity
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_invalid_token(self):
        """Test invalid or expired deletion token"""
        response = self.client.get(reverse("optimap:confirm_delete", args=["invalidtoken"]))
        messages_list = list(response.wsgi_request._messages)     
        self.assertEqual(response.status_code, 302)
        self.assertTrue(any("Invalid or expired deletion token" in str(m) for m in messages_list))

    def test_logout_and_click_delete_link(self):
        """Test scenario where user logs out and clicks deletion link"""
        self.client.logout()  # Log out user

        response = self.client.get(reverse("optimap:confirm_delete", args=[self.delete_token]))

        self.assertEqual(response.status_code, 302, "Expected a redirect (302) after clicking the deletion link while logged out.")

        expected_redirect = reverse("optimap:main")
        self.assertTrue(
            response.url.startswith(expected_redirect),
            f"Expected redirect to {expected_redirect}, but got {response.url}"
        )
