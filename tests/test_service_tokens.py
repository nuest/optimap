# SPDX-FileCopyrightText: 2026 OPTIMETA and KOMET projects <https://projects.tib.eu/komet>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests for the external-service refresh-token workflow (OpenAIRE)."""

from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core import mail
from django.template.loader import render_to_string
from django.test import TestCase, override_settings
from django.utils import timezone

from works.harvesting.openaire import get_openaire_access_token
from works.harvesting.sessions import _openaire_session, _resolve_openaire_bearer_token
from works.models import EmailLog, ServiceToken
from works.tasks import check_service_token_renewals

User = get_user_model()

EMAIL_OVERRIDES = dict(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    EMAIL_SEND_DELAY=0,
    BASE_URL="http://testserver",
)


class _Resp:
    """Minimal stand-in for a requests.Response in token-exchange tests."""

    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class AccessTokenExchangeTests(TestCase):
    def test_returns_cached_token_without_http(self):
        ServiceToken.objects.create(
            service=ServiceToken.OPENAIRE,
            refresh_token="refresh-abc",
            refresh_token_set_at=timezone.now(),
            access_token="cached-access",
            access_token_expires_at=timezone.now() + timedelta(hours=1),
        )
        with patch("works.harvesting.openaire.requests.get") as mock_get:
            token = get_openaire_access_token()
        self.assertEqual(token, "cached-access")
        mock_get.assert_not_called()

    def test_exchanges_refresh_token_when_no_valid_access_token(self):
        row = ServiceToken.objects.create(
            service=ServiceToken.OPENAIRE,
            refresh_token="refresh-abc",
            refresh_token_set_at=timezone.now(),
        )
        with patch(
            "works.harvesting.openaire.requests.get",
            return_value=_Resp({"access_token": "fresh-xyz", "expires_in": 3600}),
        ) as mock_get:
            token = get_openaire_access_token()
        self.assertEqual(token, "fresh-xyz")
        mock_get.assert_called_once()
        # query param carries the refresh token
        _, kwargs = mock_get.call_args
        self.assertEqual(kwargs["params"], {"refreshToken": "refresh-abc"})
        row.refresh_from_db()
        self.assertEqual(row.access_token, "fresh-xyz")
        self.assertTrue(row.access_token_valid())

    def test_no_refresh_token_returns_none(self):
        ServiceToken.objects.create(service=ServiceToken.OPENAIRE)
        self.assertIsNone(get_openaire_access_token())

    def test_exchange_failure_returns_none(self):
        ServiceToken.objects.create(
            service=ServiceToken.OPENAIRE,
            refresh_token="refresh-abc",
            refresh_token_set_at=timezone.now(),
        )
        with patch("works.harvesting.openaire.requests.get", side_effect=ValueError("boom")):
            self.assertIsNone(get_openaire_access_token())


class BearerResolutionTests(TestCase):
    def test_prefers_db_access_token(self):
        ServiceToken.objects.create(
            service=ServiceToken.OPENAIRE,
            refresh_token="refresh-abc",
            refresh_token_set_at=timezone.now(),
            access_token="db-access",
            access_token_expires_at=timezone.now() + timedelta(hours=1),
        )
        with override_settings(OPTIMAP_OPENAIRE_TOKEN="static-token"):
            self.assertEqual(_resolve_openaire_bearer_token(), "db-access")
            session = _openaire_session()
        self.assertEqual(session.headers["Authorization"], "Bearer db-access")

    def test_falls_back_to_static_token(self):
        with override_settings(OPTIMAP_OPENAIRE_TOKEN="static-token"):
            self.assertEqual(_resolve_openaire_bearer_token(), "static-token")
            session = _openaire_session()
        self.assertEqual(session.headers["Authorization"], "Bearer static-token")

    def test_anonymous_when_nothing_configured(self):
        with override_settings(OPTIMAP_OPENAIRE_TOKEN=""):
            self.assertIsNone(_resolve_openaire_bearer_token())
            session = _openaire_session()
        self.assertNotIn("Authorization", session.headers)


@override_settings(**EMAIL_OVERRIDES)
class RenewalReminderTests(TestCase):
    def setUp(self):
        self.staff = User.objects.create_user(
            username="staffer", email="staff@example.org", password="x", is_staff=True
        )

    def _token_expiring_in(self, days):
        # lifetime 30d by default; set_at so expiry is `days` from now
        return ServiceToken.objects.create(
            service=ServiceToken.OPENAIRE,
            refresh_token="refresh-abc",
            refresh_token_set_at=timezone.now() - timedelta(days=30 - days),
        )

    def test_emails_staff_when_within_window(self):
        self._token_expiring_in(5)  # reminder window is 9 days → due
        check_service_token_renewals()
        self.assertEqual(len(mail.outbox), 1)
        body = mail.outbox[0].body
        self.assertIn("OpenAIRE Graph API", body)
        self.assertIn("https://graph.openaire.eu/docs/apis/authentication/", body)
        self.assertIn("/admin/works/servicetoken/", body)
        self.assertEqual(EmailLog.objects.filter(status="success").count(), 1)

    def test_sends_again_on_subsequent_run_within_window(self):
        # Pure window check: every weekly run inside the window sends a reminder.
        self._token_expiring_in(5)
        check_service_token_renewals()
        self.assertEqual(len(mail.outbox), 1)
        check_service_token_renewals()
        self.assertEqual(len(mail.outbox), 2)

    def test_not_due_when_far_from_expiry(self):
        # 15 days out is outside the 9-day window → no email (task just logs).
        self._token_expiring_in(15)
        check_service_token_renewals()
        self.assertEqual(len(mail.outbox), 0)

    def test_no_token_set_does_nothing(self):
        ServiceToken.objects.create(service=ServiceToken.OPENAIRE)
        check_service_token_renewals()
        self.assertEqual(len(mail.outbox), 0)


class TemplateRendersMultipleTokensTests(TestCase):
    def test_loops_over_token_list(self):
        rendered = render_to_string(
            "email/service_token_renewal.en.txt",
            {
                "count": 2,
                "tokens": [
                    {
                        "label": "OpenAIRE Graph API",
                        "days_until_expiry": 3,
                        "expires_at": timezone.now(),
                        "docs_url": "https://docs.example/openaire",
                        "token_page_url": "https://token.example/openaire",
                        "admin_url": "http://testserver/admin/a",
                    },
                    {
                        "label": "Example Connector",
                        "days_until_expiry": 1,
                        "expires_at": timezone.now(),
                        "docs_url": "https://docs.example/other",
                        "token_page_url": "https://token.example/other",
                        "admin_url": "http://testserver/admin/b",
                    },
                ],
            },
        )
        self.assertIn("OpenAIRE Graph API", rendered)
        self.assertIn("Example Connector", rendered)
        self.assertIn("https://token.example/other", rendered)
