# SPDX-FileCopyrightText: 2026 OPTIMETA and KOMET projects <https://projects.tib.eu/komet>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests for the work-state-change notification dispatcher in
``works.notifications``."""

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.gis.geos import GeometryCollection, Point
from django.core import mail
from django.test import TestCase, override_settings

from works.models import Collection, Contribution, Source, Work
from works.notifications import notify_work_event

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
class ContributionReviewNotificationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.actor = User.objects.create_user(
            username="actor", email="actor@example.org", password="x",
        )
        cls.admin1 = User.objects.create_user(
            username="admin1", email="admin1@optimap.example", password="x", is_staff=True,
        )
        cls.admin2 = User.objects.create_user(
            username="admin2", email="admin2@optimap.example", password="x", is_staff=True,
        )
        cls.curator_a = User.objects.create_user(
            username="curatorA", email="curator-a@example.org", password="x",
        )
        cls.curator_b = User.objects.create_user(
            username="curatorB", email="curator-b@example.org", password="x",
        )
        cls.col_mw = Collection.objects.create(identifier="mw", name="Mountain Wetlands")
        cls.col_mw.curators.add(cls.curator_a)
        cls.col_agile = Collection.objects.create(identifier="agile-giss", name="AGILE-GISS")
        cls.col_agile.curators.add(cls.curator_b)

        cls.source = Source.objects.create(
            name="X", url_field="https://example.org/api", source_type="oai-pmh",
        )
        cls.work = Work.objects.create(
            title="A Study of Wetlands and Maps", status="c",
            doi="10.1234/wetlands-1",
            geometry=GeometryCollection(Point(11.0, 12.0)),
            source=cls.source,
        )
        cls.work.collections.add(cls.col_mw, cls.col_agile)

    def setUp(self):
        mail.outbox = []

    def test_admins_and_curators_are_notified(self):
        with patch("django_q.tasks.async_task", side_effect=_run_async_synchronously):
            notify_work_event(self.work, "contribution", actor=self.actor)

        recipients = sorted(addr for m in mail.outbox for addr in m.to)
        self.assertEqual(len(mail.outbox), 4)  # 2 admins + 2 curators
        self.assertIn("admin1@optimap.example", recipients)
        self.assertIn("admin2@optimap.example", recipients)
        self.assertIn("curator-a@example.org", recipients)
        self.assertIn("curator-b@example.org", recipients)
        self.assertNotIn("actor@example.org", recipients)

    def test_email_body_lists_role_summary_and_work_link(self):
        with patch("django_q.tasks.async_task", side_effect=_run_async_synchronously):
            notify_work_event(self.work, "contribution", actor=self.actor)

        body = mail.outbox[0].body
        self.assertIn("A Study of Wetlands and Maps", body)
        self.assertIn("10.1234/wetlands-1", body)
        self.assertIn("http://testserver/work/", body)
        self.assertIn("2 admins", body)
        self.assertIn("2 curators of 'AGILE-GISS', 'Mountain Wetlands'", body)
        self.assertIn("can publish", body)  # transparency caveat present
        self.assertNotIn("admin1@optimap.example", body)  # role-summary mode hides emails

    def test_actor_excluded_when_actor_is_also_admin(self):
        admin_actor = User.objects.create_user(
            username="admin_actor", email="admin-actor@optimap.example",
            password="x", is_staff=True,
        )
        with patch("django_q.tasks.async_task", side_effect=_run_async_synchronously):
            notify_work_event(self.work, "contribution", actor=admin_actor)

        recipients = sorted(addr for m in mail.outbox for addr in m.to)
        self.assertNotIn("admin-actor@optimap.example", recipients)


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    EMAIL_HOST_USER="optimap@example.org",
    BASE_URL="http://testserver",
)
class PublicationNotificationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.contrib_user = User.objects.create_user(
            username="cu", email="contributor@example.org", password="x",
        )
        cls.publishing_admin = User.objects.create_user(
            username="pa", email="admin@optimap.example", password="x", is_staff=True,
        )
        cls.source = Source.objects.create(
            name="X", url_field="https://example.org/api", source_type="oai-pmh",
        )
        cls.work = Work.objects.create(
            title="A Once-Contributed Work", status="p",
            doi="10.1234/c1",
            geometry=GeometryCollection(Point(11.0, 12.0)),
            source=cls.source,
        )
        Contribution.objects.create(
            user=cls.contrib_user, work=cls.work, kind=Contribution.SPATIAL,
        )

    def setUp(self):
        # Per-test fresh provenance so the publication-notified guard is reset.
        self.work.refresh_from_db()
        self.work.provenance = {}
        Work.objects.filter(pk=self.work.pk).update(provenance={})
        mail.outbox = []

    def test_contributor_is_notified_on_first_publish(self):
        with patch("django_q.tasks.async_task", side_effect=_run_async_synchronously):
            notify_work_event(self.work, "publish", actor=self.publishing_admin)

        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["contributor@example.org"])
        body = mail.outbox[0].body
        self.assertIn("A Once-Contributed Work", body)
        self.assertIn("Your contribution: spatial", body)
        self.assertIn("http://testserver/work/", body)
        self.assertIn("Sent only to you", body)

    def test_actor_excluded_even_if_they_contributed(self):
        # The publishing admin previously contributed too: they should NOT
        # receive the "your work was published" email — they did the publish.
        Contribution.objects.create(
            user=self.publishing_admin, work=self.work, kind=Contribution.TEMPORAL,
        )
        with patch("django_q.tasks.async_task", side_effect=_run_async_synchronously):
            notify_work_event(self.work, "publish", actor=self.publishing_admin)

        recipients = sorted(addr for m in mail.outbox for addr in m.to)
        self.assertNotIn("admin@optimap.example", recipients)
        self.assertIn("contributor@example.org", recipients)

    def test_republish_does_not_resend(self):
        with patch("django_q.tasks.async_task", side_effect=_run_async_synchronously):
            notify_work_event(self.work, "publish", actor=self.publishing_admin)
            mail.outbox = []
            # Same work flips status away and back; the second publish event
            # should not re-notify because publication_notified_at is stamped.
            self.work.refresh_from_db()
            notify_work_event(self.work, "publish", actor=self.publishing_admin)

        self.assertEqual(mail.outbox, [])

    def test_no_contributors_means_no_email(self):
        empty_work = Work.objects.create(
            title="No-one Contributed", status="p", doi="10.1234/nope",
            geometry=GeometryCollection(Point(0.0, 0.0)),
            source=self.source,
        )
        with patch("django_q.tasks.async_task", side_effect=_run_async_synchronously):
            notify_work_event(empty_work, "publish", actor=self.publishing_admin)

        self.assertEqual(mail.outbox, [])


class UnknownEventTests(TestCase):
    def test_unknown_event_is_a_noop(self):
        # Should not raise; should just log and move on.
        notify_work_event(work=None, event_type="not-registered", actor=None)
