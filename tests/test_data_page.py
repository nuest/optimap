# SPDX-FileCopyrightText: 2026 OPTIMETA and KOMET projects <https://projects.tib.eu/komet>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests for the /data page and its staff-only data-dump regeneration button."""

from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

User = get_user_model()

DATA_URL = "/data/"
REGENERATE_URL = "/data/regenerate/"
BUTTON_TEXT = "Schedule one-time generation of data dumps now"


class DataPageAdminSectionTests(TestCase):
    """The admin section + button is visible to staff only."""

    def test_button_hidden_for_anonymous(self):
        resp = self.client.get(DATA_URL)
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, BUTTON_TEXT)

    def test_button_hidden_for_non_staff(self):
        user = User.objects.create_user(username="regular", password="pw")
        self.client.force_login(user)
        resp = self.client.get(DATA_URL)
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, BUTTON_TEXT)

    def test_button_shown_for_staff(self):
        staff = User.objects.create_user(username="admin", password="pw", is_staff=True)
        self.client.force_login(staff)
        resp = self.client.get(DATA_URL)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, BUTTON_TEXT)


class ScheduleDataDumpRegenerationTests(TestCase):
    """POST /data/regenerate/ enqueues the regeneration task for staff only."""

    @mock.patch("optimap.views.async_task")
    def test_anonymous_redirected_and_no_task(self, mock_async):
        resp = self.client.post(REGENERATE_URL)
        self.assertIn(resp.status_code, (302, 403))
        mock_async.assert_not_called()

    @mock.patch("optimap.views.async_task")
    def test_non_staff_redirected_and_no_task(self, mock_async):
        user = User.objects.create_user(username="regular", password="pw")
        self.client.force_login(user)
        resp = self.client.post(REGENERATE_URL)
        self.assertIn(resp.status_code, (302, 403))
        mock_async.assert_not_called()

    @mock.patch("optimap.views.async_task")
    def test_staff_enqueues_task(self, mock_async):
        from django_q.humanhash import humanize

        mock_async.return_value = "ab12cd34ef56ab12cd34ef56ab12cd34"
        staff = User.objects.create_user(username="admin", password="pw", is_staff=True)
        self.client.force_login(staff)
        resp = self.client.post(REGENERATE_URL)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["success"])
        self.assertEqual(data["task_id"], "ab12cd34ef56ab12cd34ef56ab12cd34")
        self.assertEqual(data["task_name"], humanize("ab12cd34ef56ab12cd34ef56ab12cd34"))
        mock_async.assert_called_once_with("works.tasks.regenerate_all_data_dumps")

    @mock.patch("optimap.views.async_task")
    def test_get_not_allowed(self, mock_async):
        staff = User.objects.create_user(username="admin", password="pw", is_staff=True)
        self.client.force_login(staff)
        resp = self.client.get(REGENERATE_URL)
        self.assertEqual(resp.status_code, 405)
        mock_async.assert_not_called()

    def test_url_name_resolves(self):
        self.assertEqual(reverse("optimap:schedule-data-dump"), REGENERATE_URL)
