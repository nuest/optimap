# SPDX-FileCopyrightText: 2025 OPTIMETA and KOMET projects <https://projects.tib.eu/komet>
# SPDX-License-Identifier: GPL-3.0-or-later

import os

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "optimap.settings")
django.setup()

from django.contrib.auth import get_user_model
from django.contrib.messages import get_messages
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from works.models import BlockedEmail

User = get_user_model()


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class LoginresViewTests(TestCase):
    """Tests for loginres: redirect + flash message behaviour."""

    def setUp(self):
        self.client = Client()
        self.url = reverse("optimap:login_response")

    def test_get_redirects_to_root(self):
        response = self.client.get(self.url)
        self.assertRedirects(response, "/", fetch_redirect_response=False)

    def test_post_valid_email_redirects_to_root(self):
        response = self.client.post(self.url, {"email": "user@example.com"})
        self.assertRedirects(response, "/", fetch_redirect_response=False)

    def test_post_valid_email_sets_success_message(self):
        response = self.client.post(self.url, {"email": "user@example.com"})
        msgs = list(get_messages(response.wsgi_request))
        self.assertEqual(len(msgs), 1)
        self.assertIn("user@example.com", str(msgs[0]))

    def test_post_valid_email_message_has_persist_tag(self):
        response = self.client.post(self.url, {"email": "user@example.com"})
        msgs = list(get_messages(response.wsgi_request))
        self.assertIn("persist", msgs[0].extra_tags)

    def test_post_blocked_email_returns_error_page(self):
        BlockedEmail.objects.create(email="blocked@example.com")
        response = self.client.post(self.url, {"email": "blocked@example.com"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Login failed")

    def tearDown(self):
        BlockedEmail.objects.all().delete()


class CustomLogoutViewTests(TestCase):
    """Tests for customlogout: redirect + flash message behaviour."""

    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username="logouttest@example.com",
            email="logouttest@example.com",
            password="pass",
        )
        self.url = reverse("optimap:logout")

    def test_logout_redirects_to_root(self):
        self.client.force_login(self.user)
        response = self.client.get(self.url)
        self.assertRedirects(response, "/", fetch_redirect_response=False)

    def test_logout_sets_info_message(self):
        self.client.force_login(self.user)
        response = self.client.get(self.url)
        msgs = list(get_messages(response.wsgi_request))
        self.assertEqual(len(msgs), 1)
        self.assertIn("logged out", str(msgs[0]).lower())

    def test_logout_actually_logs_user_out(self):
        self.client.force_login(self.user)
        self.client.get(self.url)
        self.client.get(reverse("optimap:usersettings"))
        # user_settings redirects unauthenticated users to an error page (200),
        # not to a login page, so check that the user key is gone from the session.
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_logout_unauthenticated_redirects(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class ChangeUserEmailViewTests(TestCase):
    """Tests for change_useremail: redirect + flash message behaviour."""

    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username="old@example.com",
            email="old@example.com",
            password="pass",
        )
        self.client.force_login(self.user)
        self.url = reverse("optimap:changeuser")

    def test_valid_email_change_redirects_to_root(self):
        response = self.client.post(self.url, {"email_new": "new@example.com"})
        self.assertRedirects(response, "/", fetch_redirect_response=False)

    def test_valid_email_change_sets_info_message(self):
        response = self.client.post(self.url, {"email_new": "new@example.com"})
        msgs = list(get_messages(response.wsgi_request))
        self.assertEqual(len(msgs), 1)
        self.assertIn("new@example.com", str(msgs[0]))

    def test_valid_email_change_message_has_persist_tag(self):
        response = self.client.post(self.url, {"email_new": "new@example.com"})
        msgs = list(get_messages(response.wsgi_request))
        self.assertIn("persist", msgs[0].extra_tags)

    def test_valid_email_change_logs_user_out(self):
        self.client.post(self.url, {"email_new": "new@example.com"})
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_same_email_returns_error_page(self):
        response = self.client.post(self.url, {"email_new": "old@example.com"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Invalid Email Change")

    def test_blocked_email_returns_error_page(self):
        BlockedEmail.objects.create(email="blocked@example.com")
        response = self.client.post(self.url, {"email_new": "blocked@example.com"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Login failed")

    def test_already_used_email_returns_error_page(self):
        User.objects.create_user(username="other@example.com", email="other@example.com")
        response = self.client.post(self.url, {"email_new": "other@example.com"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Already In Use")

    def tearDown(self):
        BlockedEmail.objects.all().delete()
