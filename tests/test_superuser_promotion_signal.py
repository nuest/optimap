# SPDX-FileCopyrightText: 2026 OPTIMETA and KOMET projects <https://projects.tib.eu/komet>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Regression tests for the pre_save superuser-promotion signal (works/signals.py).

Guards against the regression where an unset OPTIMAP_SUPERUSER_EMAILS parsed to
[""], so every account created without an email matched and was silently
promoted to is_staff/is_superuser (broke tests.test_statistics permission
checks in CI, where the env var is unset).
"""

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

User = get_user_model()


class SuperuserPromotionSignalTests(TestCase):
    @override_settings(OPTIMAP_SUPERUSER_EMAILS=[])
    def test_no_email_not_promoted_when_list_empty(self):
        user = User.objects.create_user(username="regular", password="pw")
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)

    @override_settings(OPTIMAP_SUPERUSER_EMAILS=[])
    def test_with_email_not_promoted_when_list_empty(self):
        user = User.objects.create_user(username="someone", email="someone@example.org", password="pw")
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)

    @override_settings(OPTIMAP_SUPERUSER_EMAILS=["admin@example.org"])
    def test_blank_email_not_promoted_even_if_blank_in_list(self):
        # Defense-in-depth: a blank email must never match, even if the
        # configured list erroneously contains an empty string.
        with override_settings(OPTIMAP_SUPERUSER_EMAILS=[""]):
            user = User.objects.create_user(username="blank", password="pw")
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)

    @override_settings(OPTIMAP_SUPERUSER_EMAILS=["admin@example.org"])
    def test_matching_email_is_promoted(self):
        user = User.objects.create_user(username="admin", email="admin@example.org", password="pw")
        self.assertTrue(user.is_staff)
        self.assertTrue(user.is_superuser)
