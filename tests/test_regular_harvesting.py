# SPDX-FileCopyrightText: 2025 OPTIMETA and KOMET projects <https://projects.tib.eu/komet>
# SPDX-License-Identifier: GPL-3.0-or-later

import os
import django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'optimap.settings')
django.setup()
import unittest
from works.tasks import harvest_oai_endpoint
from django.test import TransactionTestCase, TestCase, Client
from django.core import mail
from django.utils import timezone
from django.conf import settings
from django.contrib.auth import get_user_model
from unittest.mock import patch, Mock
from django.test.utils import override_settings
from works.models import Source, Work, HarvestingEvent

User = get_user_model()

@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class HarvestRegularMetadataTestCase(TestCase):
    
    def setUp(self):
        Work.objects.all().delete()
        HarvestingEvent.objects.all().delete()

        self.user = User.objects.create_user(
            username="testuser", 
            email="testuser@example.com", 
            password="password123"
        )
        # No Collection is created here on purpose: this test exercises the
        # "Source.collection is unset" path. Harvesting must succeed and
        # produce works whose collections membership is empty.
        self.source = Source.objects.create(
            name="Test Source",
            url_field="https://example.com/oai?verb=ListRecords&metadataPrefix=oai_dc",
            tags="test,harvest",
        )

    @patch("works.tasks._oai_session")
    @patch("works.tasks.parse_oai_xml_and_save_works")
    def test_harvest_regular_metadata_sends_email(self, mock_parser, mock_session_factory):
        fake_response = Mock()
        fake_response.ok = True
        fake_response.status_code = 200
        fake_response.headers = {"Content-Type": "application/xml"}
        fake_response.content = b"<OAI-PMH><ListRecords></ListRecords></OAI-PMH>"
        mock_session = Mock()
        mock_session.get.return_value = fake_response
        mock_session_factory.return_value = mock_session

        def fake_parser_func(content, event, max_records=None, warning_collector=None, update_existing=False):
            Work.objects.create(
                title="Test Publication 1",
                doi="10.1000/1",
                job=event,
                timeperiod_startdate=[],
                timeperiod_enddate=[],
                geometry=None
            )
            Work.objects.create(
                title="Test Publication 2",
                doi="10.1000/2",
                job=event,
                timeperiod_startdate=[],
                timeperiod_enddate=[],
                geometry=None
            )
            return 2, 0, 0  # Two publications added, no spatial or temporal metadata

        mock_parser.side_effect = fake_parser_func

        mail.outbox = []

        harvest_oai_endpoint(self.source.id, self.user)

        event = HarvestingEvent.objects.filter(source=self.source).latest("started_at")

        new_count = Work.objects.filter(job=event).count()
        self.assertEqual(new_count, 2, "Two publications should be created during harvest.")

        spatial_count = Work.objects.filter(job=event).exclude(geometry__isnull=True).count()
        self.assertEqual(spatial_count, 0, "No publication should have spatial metadata.")

        temporal_count = Work.objects.filter(job=event).exclude(timeperiod_startdate=[]).count()
        self.assertEqual(temporal_count, 0, "No publication has temporal metadata.")

        self.assertEqual(len(mail.outbox), 1, "One email should be sent to the user.")
        email = mail.outbox[0]
        self.assertIn("Harvesting Completed", email.subject)
        self.assertIn("Number of added articles: 2", email.body)
        self.assertIn("Number of articles with spatial metadata: 0", email.body)
        self.assertIn("Number of articles with temporal metadata: 0", email.body)
        # No collection set on this source — email falls back to the source name.
        self.assertIn(self.source.name, email.body)
        self.assertIn(self.source.url_field, email.body)
        self.assertIn(event.started_at.strftime("%Y-%m-%d"), email.body)
