# SPDX-FileCopyrightText: 2025 OPTIMETA and KOMET projects <https://projects.tib.eu/komet>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests to verify publication status workflow compliance."""
from django.test import TestCase
from django.contrib.gis.geos import Point, GeometryCollection
from works.models import Work, Source, STATUS_CHOICES
from django.contrib.auth import get_user_model

User = get_user_model()


class StatusWorkflowComplianceTests(TestCase):
    """Verify all statuses are properly defined and workflow is enforced."""

    def setUp(self):
        self.source = Source.objects.create(
            name='Test Source',
            is_oa=True,
            is_preprint=False
        )

        self.user = User.objects.create_user(
            username='user@example.com',
            email='user@example.com',
            password='testpass123'
        )

        self.admin = User.objects.create_user(
            username='admin@example.com',
            email='admin@example.com',
            password='adminpass123',
            is_staff=True,
            is_superuser=True
        )

    def test_all_six_statuses_defined(self):
        """Verify all 6 statuses from README are defined in model."""
        expected_statuses = {
            'd': 'Draft',
            'h': 'Harvested',
            'c': 'Contributed',
            'p': 'Published',
            't': 'Testing',
            'w': 'Withdrawn'
        }

        actual_statuses = dict(STATUS_CHOICES)
        self.assertEqual(actual_statuses, expected_statuses)
        self.assertEqual(len(STATUS_CHOICES), 6)

    def test_harvested_status_visibility(self):
        """Harvested landing pages are visible to non-admins.

        The /contribute/ listing hands users to the work landing page where
        the contribution form lives, so a 404 there would break the flow.
        See works/views/work_views.py:work_landing — Drafts ('d'), Testing
        ('t'), and Withdrawn ('w') remain admin-only.
        """
        pub = Work.objects.create(
            title='Harvested Publication',
            status='h',
            doi='10.1234/harvested',
            source=self.source
        )

        # Non-admin can access — needed for the contribute flow.
        response = self.client.get(f'/work/{pub.doi}/')
        self.assertEqual(response.status_code, 200)

        # Admin can access too.
        self.client.login(username='admin@example.com', password='adminpass123')
        response = self.client.get(f'/work/{pub.doi}/')
        self.assertEqual(response.status_code, 200)

    def test_contributed_status_visibility(self):
        """Contributed landing pages are visible to non-admins.

        After a successful contribution flips a work from 'h' to 'c', the
        post-submit reload would 404 if 'c' were admin-only. See
        works/views/work_views.py:work_landing for the rationale.
        """
        pub = Work.objects.create(
            title='Contributed Publication',
            status='c',
            doi='10.1234/contributed',
            source=self.source,
            geometry=GeometryCollection(Point(13.405, 52.52))
        )

        # Non-admin can access — keeps the post-contribute reload working.
        response = self.client.get(f'/work/{pub.doi}/')
        self.assertEqual(response.status_code, 200)

        # Admin can access too.
        self.client.login(username='admin@example.com', password='adminpass123')
        response = self.client.get(f'/work/{pub.doi}/')
        self.assertEqual(response.status_code, 200)

    def test_published_status_visibility(self):
        """Published publications should be visible to all users."""
        pub = Work.objects.create(
            title='Published Publication',
            status='p',
            doi='10.1234/published',
            source=self.source,
            geometry=GeometryCollection(Point(13.405, 52.52))
        )

        # Non-admin can access
        response = self.client.get(f'/work/{pub.doi}/')
        self.assertEqual(response.status_code, 200)

    def test_draft_status_visibility(self):
        """Draft publications should not be visible to non-admin users."""
        pub = Work.objects.create(
            title='Draft Publication',
            status='d',
            doi='10.1234/draft',
            source=self.source
        )

        # Non-admin cannot access
        response = self.client.get(f'/work/{pub.doi}/')
        self.assertEqual(response.status_code, 404)

        # Admin can access
        self.client.login(username='admin@example.com', password='adminpass123')
        response = self.client.get(f'/work/{pub.doi}/')
        self.assertEqual(response.status_code, 200)

    def test_testing_status_visibility(self):
        """Testing publications should not be visible to non-admin users."""
        pub = Work.objects.create(
            title='Testing Publication',
            status='t',
            doi='10.1234/testing',
            source=self.source
        )

        # Non-admin cannot access
        response = self.client.get(f'/work/{pub.doi}/')
        self.assertEqual(response.status_code, 404)

        # Admin can access
        self.client.login(username='admin@example.com', password='adminpass123')
        response = self.client.get(f'/work/{pub.doi}/')
        self.assertEqual(response.status_code, 200)

    def test_withdrawn_status_visibility(self):
        """Withdrawn publications should not be visible to non-admin users."""
        pub = Work.objects.create(
            title='Withdrawn Publication',
            status='w',
            doi='10.1234/withdrawn',
            source=self.source
        )

        # Non-admin cannot access
        response = self.client.get(f'/work/{pub.doi}/')
        self.assertEqual(response.status_code, 404)

        # Admin can access
        self.client.login(username='admin@example.com', password='adminpass123')
        response = self.client.get(f'/work/{pub.doi}/')
        self.assertEqual(response.status_code, 200)

    def test_contribution_only_allowed_for_harvested(self):
        """Users can only contribute to harvested publications."""
        self.client.login(username='user@example.com', password='testpass123')

        # Test each non-harvested status
        for status_code, status_name in [('d', 'Draft'), ('p', 'Published'),
                                         ('t', 'Testing'), ('w', 'Withdrawn'),
                                         ('c', 'Contributed')]:
            pub = Work.objects.create(
                title=f'{status_name} Publication',
                status=status_code,
                doi=f'10.1234/{status_code}',
                source=self.source
            )

            response = self.client.post(
                f'/work/{pub.doi}/contribute-geometry/',
                data='{"temporal_extent": {"start_date": "2020"}}',
                content_type='application/json'
            )

            self.assertEqual(response.status_code, 400)
            data = response.json()
            self.assertIn('Can only contribute to harvested publications', data['error'])

    def test_api_only_returns_published_for_non_admin(self):
        """API should only return published publications to non-admin users."""
        # Create one of each status
        for status_code, status_name in STATUS_CHOICES:
            Work.objects.create(
                title=f'{status_name} Publication',
                status=status_code,
                doi=f'10.1234/{status_code}',
                source=self.source,
                geometry=GeometryCollection(Point(13.405, 52.52))
            )

        # Non-admin request
        response = self.client.get('/api/v1/works/')
        self.assertEqual(response.status_code, 200)
        data = response.json()

        # Should only return published publications
        self.assertEqual(data['count'], 1)
        self.assertEqual(data['results']['features'][0]['properties']['doi'], '10.1234/p')

    def test_unpublish_creates_draft_status(self):
        """Unpublishing should change status from Published to Draft."""
        pub = Work.objects.create(
            title='Published Publication',
            status='p',
            doi='10.1234/published',
            source=self.source,
            geometry=GeometryCollection(Point(13.405, 52.52))
        )

        self.client.login(username='admin@example.com', password='adminpass123')
        response = self.client.post(f'/work/{pub.doi}/unpublish/', content_type='application/json')

        self.assertEqual(response.status_code, 200)
        pub.refresh_from_db()
        self.assertEqual(pub.status, 'd')  # Draft
        events = pub.provenance.get('events', [])
        self.assertTrue(any(
            ev.get('type') == 'unpublish' and ev.get('status_from') == 'p' and ev.get('status_to') == 'd'
            for ev in events
        ), f"unpublish event not found in {events!r}")
