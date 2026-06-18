# SPDX-FileCopyrightText: 2026 OPTIMETA and KOMET projects <https://projects.tib.eu/komet>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests for the work-state-change notification dispatcher in
``works.notifications``."""

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.gis.geos import GeometryCollection, Point
from django.core import mail
from django.test import TestCase, override_settings

from works.models import Collection, Contribution, EmailLog, Source, Work
from works.notifications import notify_curator_change, notify_work_event

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
            username="actor",
            email="actor@example.org",
            password="x",
        )
        cls.admin1 = User.objects.create_user(
            username="admin1",
            email="admin1@optimap.example",
            password="x",
            is_staff=True,
        )
        cls.admin2 = User.objects.create_user(
            username="admin2",
            email="admin2@optimap.example",
            password="x",
            is_staff=True,
        )
        cls.curator_a = User.objects.create_user(
            username="curatorA",
            email="curator-a@example.org",
            password="x",
        )
        cls.curator_b = User.objects.create_user(
            username="curatorB",
            email="curator-b@example.org",
            password="x",
        )
        cls.col_mw = Collection.objects.create(identifier="mw", name="Mountain Wetlands")
        cls.col_mw.curators.add(cls.curator_a)
        cls.col_agile = Collection.objects.create(identifier="agile-giss", name="AGILE-GISS")
        cls.col_agile.curators.add(cls.curator_b)

        cls.source = Source.objects.create(
            name="X",
            url_field="https://example.org/api",
            source_type="oai-pmh",
        )
        cls.work = Work.objects.create(
            title="A Study of Wetlands and Maps",
            status="c",
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
            username="admin_actor",
            email="admin-actor@optimap.example",
            password="x",
            is_staff=True,
        )
        with patch("django_q.tasks.async_task", side_effect=_run_async_synchronously):
            notify_work_event(self.work, "contribution", actor=admin_actor)

        recipients = sorted(addr for m in mail.outbox for addr in m.to)
        self.assertNotIn("admin-actor@optimap.example", recipients)

    def test_inactive_staff_and_curator_are_not_notified(self):
        # A deactivated (is_active=False) staff account and curator must not
        # receive contribution-review emails.
        inactive_admin = User.objects.create_user(
            username="inactive_admin",
            email="inactive-admin@optimap.example",
            password="x",
            is_staff=True,
            is_active=False,
        )
        inactive_curator = User.objects.create_user(
            username="inactive_curator",
            email="inactive-curator@example.org",
            password="x",
            is_active=False,
        )
        self.col_mw.curators.add(inactive_curator)
        with patch("django_q.tasks.async_task", side_effect=_run_async_synchronously):
            notify_work_event(self.work, "contribution", actor=self.actor)

        recipients = sorted(addr for m in mail.outbox for addr in m.to)
        self.assertNotIn(inactive_admin.email, recipients)
        self.assertNotIn(inactive_curator.email, recipients)
        # Active recipients are unaffected.
        self.assertIn("admin1@optimap.example", recipients)


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    EMAIL_HOST_USER="optimap@example.org",
    BASE_URL="http://testserver",
)
class PublicationNotificationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.contrib_user = User.objects.create_user(
            username="cu",
            email="contributor@example.org",
            password="x",
        )
        cls.publishing_admin = User.objects.create_user(
            username="pa",
            email="admin@optimap.example",
            password="x",
            is_staff=True,
        )
        cls.source = Source.objects.create(
            name="X",
            url_field="https://example.org/api",
            source_type="oai-pmh",
        )
        cls.work = Work.objects.create(
            title="A Once-Contributed Work",
            status="p",
            doi="10.1234/c1",
            geometry=GeometryCollection(Point(11.0, 12.0)),
            source=cls.source,
        )
        Contribution.objects.create(
            user=cls.contrib_user,
            work=cls.work,
            kind=Contribution.SPATIAL,
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
            user=self.publishing_admin,
            work=self.work,
            kind=Contribution.TEMPORAL,
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
            title="No-one Contributed",
            status="p",
            doi="10.1234/nope",
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


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    EMAIL_HOST_USER="optimap@example.org",
    BASE_URL="http://testserver",
)
class WorkEventOptOutTests(TestCase):
    """Per-user ``UserProfile.notify_work_events`` toggle.

    Default is ``True`` (collaborators stay in the loop), but a user who
    flips it to ``False`` must not receive contribution-review or
    publication-thank-you emails. The actor is unaffected: they're already
    excluded from recipient sets independently of the opt-out flag.
    """

    @classmethod
    def setUpTestData(cls):
        cls.actor = User.objects.create_user(
            username="actor",
            email="actor@example.org",
            password="x",
        )
        cls.opted_in_admin = User.objects.create_user(
            username="optin_admin",
            email="optin-admin@optimap.example",
            password="x",
            is_staff=True,
        )
        cls.opted_out_admin = User.objects.create_user(
            username="optout_admin",
            email="optout-admin@optimap.example",
            password="x",
            is_staff=True,
        )
        cls.opted_out_admin.userprofile.notify_work_events = False
        cls.opted_out_admin.userprofile.save()

        cls.opted_in_curator = User.objects.create_user(
            username="optin_cur",
            email="optin-curator@example.org",
            password="x",
        )
        cls.opted_out_curator = User.objects.create_user(
            username="optout_cur",
            email="optout-curator@example.org",
            password="x",
        )
        cls.opted_out_curator.userprofile.notify_work_events = False
        cls.opted_out_curator.userprofile.save()

        cls.col = Collection.objects.create(identifier="opt", name="OptOut Collection")
        cls.col.curators.add(cls.opted_in_curator, cls.opted_out_curator)

        cls.source = Source.objects.create(
            name="X",
            url_field="https://example.org/api",
            source_type="oai-pmh",
        )
        cls.work = Work.objects.create(
            title="Opt-Out Coverage Work",
            status="c",
            doi="10.1234/optout-1",
            geometry=GeometryCollection(Point(11.0, 12.0)),
            source=cls.source,
        )
        cls.work.collections.add(cls.col)

    def setUp(self):
        mail.outbox = []

    def test_contribution_email_skips_opted_out_admins(self):
        with patch("django_q.tasks.async_task", side_effect=_run_async_synchronously):
            notify_work_event(self.work, "contribution", actor=self.actor)

        recipients = sorted(addr for m in mail.outbox for addr in m.to)
        self.assertIn("optin-admin@optimap.example", recipients)
        self.assertNotIn("optout-admin@optimap.example", recipients)

    def test_contribution_email_skips_opted_out_curators(self):
        with patch("django_q.tasks.async_task", side_effect=_run_async_synchronously):
            notify_work_event(self.work, "contribution", actor=self.actor)

        recipients = sorted(addr for m in mail.outbox for addr in m.to)
        self.assertIn("optin-curator@example.org", recipients)
        self.assertNotIn("optout-curator@example.org", recipients)

    def test_role_summary_does_not_count_opted_out_curators(self):
        # The transparency block should describe who actually got notified —
        # it would be misleading to claim 2 curators were emailed when one
        # opted out.
        with patch("django_q.tasks.async_task", side_effect=_run_async_synchronously):
            notify_work_event(self.work, "contribution", actor=self.actor)

        body = mail.outbox[0].body
        self.assertIn("1 curator of 'OptOut Collection'", body)
        self.assertNotIn("2 curators", body)

    def test_publish_email_skips_opted_out_contributor(self):
        # A contributor with notify_work_events=False does NOT get the
        # "your work was published" email.
        published = Work.objects.create(
            title="Published Work",
            status="p",
            doi="10.1234/pub-1",
            geometry=GeometryCollection(Point(0.0, 0.0)),
            source=self.source,
        )
        Contribution.objects.create(
            user=self.opted_in_curator,
            work=published,
            kind=Contribution.SPATIAL,
        )
        Contribution.objects.create(
            user=self.opted_out_curator,
            work=published,
            kind=Contribution.TEMPORAL,
        )

        with patch("django_q.tasks.async_task", side_effect=_run_async_synchronously):
            notify_work_event(published, "publish", actor=self.actor)

        recipients = sorted(addr for m in mail.outbox for addr in m.to)
        self.assertIn("optin-curator@example.org", recipients)
        self.assertNotIn("optout-curator@example.org", recipients)

    def test_default_value_is_opted_in(self):
        # Sanity check: a freshly created user gets a UserProfile via signal
        # with notify_work_events=True, so they receive the emails by default.
        self.assertTrue(self.opted_in_admin.userprofile.notify_work_events)
        self.assertTrue(self.opted_in_curator.userprofile.notify_work_events)


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    EMAIL_HOST_USER="optimap@example.org",
    BASE_URL="http://testserver",
)
class CuratorChangeNotificationTests(TestCase):
    """Tests for notify_curator_change / send_curator_change_email."""

    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_user(
            username="curator-admin",
            email="curator-admin@example.org",
            password="x",
            is_staff=True,
        )
        cls.existing_curator = User.objects.create_user(
            username="existing-curator",
            email="existing@example.org",
            password="x",
        )
        cls.new_curator = User.objects.create_user(
            username="new-curator",
            email="new@example.org",
            password="x",
        )
        cls.col = Collection.objects.create(identifier="notify-col", name="Notify Col")
        cls.col.curators.add(cls.existing_curator)

    def setUp(self):
        mail.outbox = []

    def _add_and_notify(self, actor=None):
        """Add new_curator then fire the notification synchronously."""
        self.col.curators.add(self.new_curator)
        with patch("django_q.tasks.async_task", side_effect=_run_async_synchronously):
            notify_curator_change(self.col, self.new_curator, "added", actor=actor or self.admin)

    def _remove_and_notify(self, actor=None):
        """Remove new_curator (assumes already added) then fire synchronously."""
        self.col.curators.remove(self.new_curator)
        with patch("django_q.tasks.async_task", side_effect=_run_async_synchronously):
            notify_curator_change(self.col, self.new_curator, "removed", actor=actor or self.admin)

    def tearDown(self):
        # Keep the curator list clean between tests.
        self.col.curators.remove(self.new_curator)

    # --- recipients ---

    def test_add_notifies_all_curators_admins_and_actor(self):
        self._add_and_notify()
        recipients = sorted(addr for m in mail.outbox for addr in m.to)
        self.assertIn("curator-admin@example.org", recipients)  # admin + actor
        self.assertIn("existing@example.org", recipients)  # existing curator
        self.assertIn("new@example.org", recipients)  # newly added curator

    def test_remove_notifies_removed_curator_too(self):
        self.col.curators.add(self.new_curator)
        self._remove_and_notify()
        recipients = sorted(addr for m in mail.outbox for addr in m.to)
        self.assertIn("new@example.org", recipients)  # removed — still gets mail

    def test_no_duplicate_emails_when_actor_is_also_admin(self):
        # Admin acting as actor: only one email per address.
        self._add_and_notify(actor=self.admin)
        admin_mails = [m for m in mail.outbox if "curator-admin@example.org" in m.to]
        self.assertEqual(len(admin_mails), 1)

    # --- subject / body ---

    def test_subject_contains_action_and_collection_name(self):
        self._add_and_notify()
        subjects = [m.subject for m in mail.outbox]
        self.assertTrue(all("added" in s and "Notify Col" in s for s in subjects))

    def test_body_names_changed_user_and_actor(self):
        self._add_and_notify()
        body = mail.outbox[0].body
        self.assertIn("new@example.org", body)
        self.assertIn("curator-admin@example.org", body)

    def test_body_lists_current_curators_after_add(self):
        self._add_and_notify()
        body = mail.outbox[0].body
        self.assertIn("existing@example.org", body)
        self.assertIn("new@example.org", body)

    # --- EmailLog ---

    def test_emaillog_written_on_successful_send(self):
        before = EmailLog.objects.count()
        self._add_and_notify()
        after = EmailLog.objects.count()
        self.assertGreater(after, before)
        log = EmailLog.objects.filter(subject__icontains="curator added").last()
        self.assertIsNotNone(log)
        self.assertEqual(log.status, "success")
        self.assertEqual(log.trigger_source, "scheduled")

    def test_emaillog_written_for_every_recipient(self):
        self._add_and_notify()
        logs = EmailLog.objects.filter(subject__icontains="curator added")
        logged_recipients = set(logs.values_list("recipient_email", flat=True))
        self.assertIn("curator-admin@example.org", logged_recipients)
        self.assertIn("existing@example.org", logged_recipients)
        self.assertIn("new@example.org", logged_recipients)

    def test_emaillog_written_on_remove(self):
        self.col.curators.add(self.new_curator)
        self._remove_and_notify()
        log = EmailLog.objects.filter(subject__icontains="curator removed").last()
        self.assertIsNotNone(log)
        self.assertEqual(log.status, "success")

    # --- active + opt-out gating ---

    def test_inactive_curator_and_admin_are_not_notified(self):
        inactive_admin = User.objects.create_user(
            username="inactive-cc-admin",
            email="inactive-cc-admin@example.org",
            password="x",
            is_staff=True,
            is_active=False,
        )
        inactive_curator = User.objects.create_user(
            username="inactive-cc-curator",
            email="inactive-cc-curator@example.org",
            password="x",
            is_active=False,
        )
        self.col.curators.add(inactive_curator)
        self._add_and_notify()
        recipients = sorted(addr for m in mail.outbox for addr in m.to)
        self.assertNotIn(inactive_admin.email, recipients)
        self.assertNotIn(inactive_curator.email, recipients)

    def test_opted_out_admin_is_not_notified(self):
        # notify_work_events opt-out now gates curator-change emails too.
        opted_out_admin = User.objects.create_user(
            username="optout-cc-admin",
            email="optout-cc-admin@example.org",
            password="x",
            is_staff=True,
        )
        opted_out_admin.userprofile.notify_work_events = False
        opted_out_admin.userprofile.save()
        self._add_and_notify()
        recipients = sorted(addr for m in mail.outbox for addr in m.to)
        self.assertNotIn(opted_out_admin.email, recipients)
        # An opted-in admin still receives it.
        self.assertIn("curator-admin@example.org", recipients)
