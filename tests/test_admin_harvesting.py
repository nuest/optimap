# SPDX-FileCopyrightText: 2026 OPTIMETA and KOMET projects <https://projects.tib.eu/komet>
# SPDX-License-Identifier: GPL-3.0-or-later

import os
from unittest.mock import patch

import django
import responses
from django.contrib import admin as admin_site
from django.test import RequestFactory, TestCase
from django.urls import reverse

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'optimap.settings')
django.setup()

from django.contrib.auth import get_user_model

from works.admin import (
    HarvestingEventAdmin,
    SourceAdmin,
    retry_event,
    schedule_harvesting,
    trigger_harvesting_for_specific,
)
from works.models import HarvestingEvent, Source
from works.tasks import harvest_oai_endpoint

User = get_user_model()


def _make_source(**overrides):
    defaults = dict(
        name="Test Source",
        url_field="http://example.org/oai",
        harvest_interval_minutes=60,
    )
    defaults.update(overrides)
    return Source.objects.create(**defaults)


class HarvestingEventLogPersistenceTest(TestCase):
    """The harvest_oai_endpoint task must persist log_text + counts/error on the event."""

    @responses.activate
    def test_failure_persists_error_and_log(self):
        source = _make_source(url_field="http://does-not-exist.invalid/oai")
        responses.add(
            responses.GET,
            "http://does-not-exist.invalid/oai",
            status=503,
            body="upstream down",
        )

        harvest_oai_endpoint(source.id, user=None)

        event = HarvestingEvent.objects.filter(source=source).latest("started_at")
        self.assertEqual(event.status, "failed")
        self.assertNotEqual(event.error_message, "")
        self.assertIn("503", event.error_message)
        self.assertNotEqual(event.log_text, "")
        self.assertIsNone(event.records_added)

    @responses.activate
    def test_failure_with_user_id_int_does_not_crash(self):
        # Regression: admin actions enqueue with user.id (int), and harvest_oai_endpoint
        # used to assume `user` was a User instance — `user.email` blew up with
        # AttributeError on the failure-notification branch. The task must accept an int.
        admin = User.objects.create_superuser(
            username="opsadmin", email="ops@example.org", password="x"
        )
        source = _make_source(url_field="http://does-not-exist.invalid/oai")
        responses.add(
            responses.GET,
            "http://does-not-exist.invalid/oai",
            status=503,
            body="upstream down",
        )

        harvest_oai_endpoint(source.id, user=admin.id)

        event = HarvestingEvent.objects.filter(source=source).latest("started_at")
        self.assertEqual(event.status, "failed")

    @responses.activate
    def test_success_persists_counts_and_log(self):
        source = _make_source(url_field="http://example.org/oai")
        # Minimal valid OAI-PMH ListRecords response with zero records — exercises the
        # success branch without needing real publication parsing.
        empty_oai_xml = b"""<?xml version="1.0" encoding="UTF-8"?>
<OAI-PMH xmlns="http://www.openarchives.org/OAI/2.0/">
  <responseDate>2026-04-30T00:00:00Z</responseDate>
  <ListRecords/>
</OAI-PMH>"""
        responses.add(
            responses.GET,
            "http://example.org/oai",
            body=empty_oai_xml,
            content_type="text/xml",
        )

        harvest_oai_endpoint(source.id, user=None)

        event = HarvestingEvent.objects.filter(source=source).latest("started_at")
        self.assertEqual(event.status, "completed")
        self.assertEqual(event.records_added, 0)
        self.assertEqual(event.records_with_spatial, 0)
        self.assertEqual(event.records_with_temporal, 0)
        # log_text always populated by HarvestWarningCollector.get_summary()
        self.assertNotEqual(event.log_text, "")


class SourceAdminRegistrationTest(TestCase):
    def test_source_is_registered_with_source_admin(self):
        self.assertIn(Source, admin_site.site._registry)
        self.assertIsInstance(admin_site.site._registry[Source], SourceAdmin)

    def test_harvestingevent_is_registered_with_event_admin(self):
        self.assertIn(HarvestingEvent, admin_site.site._registry)
        self.assertIsInstance(admin_site.site._registry[HarvestingEvent], HarvestingEventAdmin)

    def test_harvestingevent_admin_disallows_add(self):
        ma = admin_site.site._registry[HarvestingEvent]
        rf = RequestFactory()
        request = rf.get("/admin/works/harvestingevent/")
        self.assertFalse(ma.has_add_permission(request))


class HarvestAdminActionsTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser(
            username="admin", email="admin@example.org", password="x"
        )
        self.source = _make_source()
        self.rf = RequestFactory()

    def _request(self):
        request = self.rf.post("/admin/works/source/")
        request.user = self.user
        # The action calls modeladmin.message_user; that needs a messages framework.
        # We bypass the storage by attaching a no-op _messages.
        from django.contrib.messages.storage.fallback import FallbackStorage

        setattr(request, "session", {})
        setattr(request, "_messages", FallbackStorage(request))
        return request

    @patch("works.admin.async_task")
    def test_trigger_action_enqueues_via_async_task_with_works_dotted_path(self, mock_async):
        ma = admin_site.site._registry[Source]
        request = self._request()
        trigger_harvesting_for_specific(ma, request, Source.objects.filter(id=self.source.id))

        self.assertEqual(mock_async.call_count, 1)
        args, _ = mock_async.call_args
        self.assertEqual(args[0], "works.tasks.harvest_oai_endpoint")
        self.assertEqual(args[1], self.source.id)

    def test_schedule_action_uses_works_dotted_path(self):
        ma = admin_site.site._registry[Source]
        request = self._request()
        # Clear any auto-created Schedule rows from Source.save().
        from django_q.models import Schedule

        Schedule.objects.filter(name=f"Manual Harvest Source {self.source.id}").delete()
        schedule_harvesting(ma, request, Source.objects.filter(id=self.source.id))

        sched = Schedule.objects.get(name=f"Manual Harvest Source {self.source.id}")
        self.assertEqual(sched.func, "works.tasks.harvest_oai_endpoint")

    @patch("works.admin.async_task")
    def test_trigger_action_dispatches_by_source_type_for_mountain_wetlands(self, mock_async):
        mwr = _make_source(
            name="MWR", url_field="https://andes.example.org/api/v1/items/",
            source_type="mountain-wetlands",
        )
        ma = admin_site.site._registry[Source]
        request = self._request()
        trigger_harvesting_for_specific(ma, request, Source.objects.filter(id=mwr.id))

        self.assertEqual(mock_async.call_count, 1)
        args, _ = mock_async.call_args
        self.assertEqual(args[0], "works.tasks.harvest_mountain_wetlands")
        self.assertEqual(args[1], mwr.id)

    @patch("works.admin.async_task")
    def test_trigger_action_dispatches_by_source_type_for_rss(self, mock_async):
        rss = _make_source(
            name="RSS", url_field="https://example.org/feed.rss", source_type="rss",
        )
        ma = admin_site.site._registry[Source]
        request = self._request()
        trigger_harvesting_for_specific(ma, request, Source.objects.filter(id=rss.id))

        self.assertEqual(mock_async.call_count, 1)
        args, _ = mock_async.call_args
        self.assertEqual(args[0], "works.tasks.harvest_rss_endpoint")

    def test_schedule_action_picks_task_by_source_type(self):
        from django_q.models import Schedule
        mwr = _make_source(
            name="MWR-sch", url_field="https://andes.example.org/api/v1/items2/",
            source_type="mountain-wetlands",
        )
        ma = admin_site.site._registry[Source]
        request = self._request()
        Schedule.objects.filter(name=f"Manual Harvest Source {mwr.id}").delete()
        schedule_harvesting(ma, request, Source.objects.filter(id=mwr.id))

        sched = Schedule.objects.get(name=f"Manual Harvest Source {mwr.id}")
        self.assertEqual(sched.func, "works.tasks.harvest_mountain_wetlands")

    @patch("works.admin.async_task")
    def test_retry_event_dispatches_by_current_source_type(self, mock_async):
        mwr = _make_source(
            name="MWR-retry", url_field="https://andes.example.org/api/v1/items3/",
            source_type="mountain-wetlands",
        )
        event = HarvestingEvent.objects.create(source=mwr, status="failed")
        ma = admin_site.site._registry[HarvestingEvent]
        request = self.rf.post("/admin/works/harvestingevent/")
        request.user = self.user
        from django.contrib.messages.storage.fallback import FallbackStorage
        setattr(request, "session", {})
        setattr(request, "_messages", FallbackStorage(request))

        retry_event(ma, request, HarvestingEvent.objects.filter(id=event.id))

        self.assertEqual(mock_async.call_count, 1)
        args, _ = mock_async.call_args
        self.assertEqual(args[0], "works.tasks.harvest_mountain_wetlands")

    @patch("works.admin.async_task")
    def test_retry_event_action_enqueues_per_event(self, mock_async):
        ma = admin_site.site._registry[HarvestingEvent]
        event = HarvestingEvent.objects.create(source=self.source, status="failed")
        request = self.rf.post("/admin/works/harvestingevent/")
        request.user = self.user
        from django.contrib.messages.storage.fallback import FallbackStorage

        setattr(request, "session", {})
        setattr(request, "_messages", FallbackStorage(request))

        retry_event(ma, request, HarvestingEvent.objects.filter(id=event.id))

        self.assertEqual(mock_async.call_count, 1)
        args, _ = mock_async.call_args
        self.assertEqual(args[0], "works.tasks.harvest_oai_endpoint")
        self.assertEqual(args[1], self.source.id)


class HarvestingEventAdminChangeViewTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser(
            username="admin", email="admin@example.org", password="x"
        )
        self.client.force_login(self.user)
        self.source = _make_source()
        self.event = HarvestingEvent.objects.create(
            source=self.source,
            status="failed",
            error_message="Boom: upstream returned 503",
            log_text="🔴 ERROR: something blew up\n🟡 WARNING: also this",
            records_added=None,
        )

    def test_change_view_renders_log_and_error(self):
        url = reverse("admin:works_harvestingevent_change", args=[self.event.id])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Boom: upstream returned 503")
        self.assertContains(response, "something blew up")

    def test_changelist_renders(self):
        url = reverse("admin:works_harvestingevent_changelist")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)


class SourceScheduleTest(TestCase):
    """Source.save() must not queue every source to fire immediately."""

    def test_first_run_is_deferred_by_one_interval(self):
        # Regression: Schedule.next_run defaults to timezone.now, so brand-new
        # sources (e.g. those bulk-created by `--insert-sources`) all fired on
        # the next cluster tick. Source.save() must set next_run = now + interval.
        from django.utils import timezone
        from datetime import timedelta
        from django_q.models import Schedule

        before = timezone.now()
        source = _make_source(name="Deferred", harvest_interval_minutes=120)
        sched = Schedule.objects.get(name=f"Harvest Source {source.id}")

        expected_floor = before + timedelta(minutes=120)
        self.assertGreaterEqual(
            sched.next_run, expected_floor,
            "next_run must be at least one interval in the future after Source.save()",
        )

    def test_unrelated_save_does_not_reset_next_run(self):
        # Regression: Source.save() previously did delete-and-recreate on every save,
        # which reset next_run to "now" on any unrelated edit (e.g. last_harvest).
        from django_q.models import Schedule

        source = _make_source(name="Stable", harvest_interval_minutes=120)
        sched = Schedule.objects.get(name=f"Harvest Source {source.id}")
        original_next_run = sched.next_run
        original_id = sched.id

        source.publisher_name = "Some Publisher"
        source.save()

        sched_after = Schedule.objects.get(name=f"Harvest Source {source.id}")
        self.assertEqual(sched_after.id, original_id, "schedule row must be preserved")
        self.assertEqual(sched_after.next_run, original_next_run)

    def test_interval_change_recreates_schedule(self):
        from django_q.models import Schedule

        source = _make_source(name="Reinterval", harvest_interval_minutes=120)
        original_id = Schedule.objects.get(name=f"Harvest Source {source.id}").id

        source.harvest_interval_minutes = 60
        source.save()

        sched = Schedule.objects.get(name=f"Harvest Source {source.id}")
        self.assertNotEqual(sched.id, original_id)
        self.assertEqual(sched.minutes, 60)


class SourceAdminChangelistTest(TestCase):
    """The Source changelist must render with sources that have / don't have events."""

    def setUp(self):
        self.user = User.objects.create_superuser(
            username="admin", email="admin@example.org", password="x"
        )
        self.client.force_login(self.user)

    def test_changelist_renders_when_source_has_events(self):
        # Regression: latest_event_status used format_html with a strftime spec, which
        # ValueError'd because format_html stringifies args before applying the spec.
        source = _make_source(name="With Events")
        HarvestingEvent.objects.create(source=source, status="completed")

        url = reverse("admin:works_source_changelist")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "With Events")

    def test_changelist_renders_when_source_has_no_events(self):
        _make_source(name="No Events")
        url = reverse("admin:works_source_changelist")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "No Events")
