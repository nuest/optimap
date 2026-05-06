# SPDX-FileCopyrightText: 2026 OPTIMETA and KOMET projects <https://projects.tib.eu/komet>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests for the Collection model, /collections/ pages, sitemaps, and the
curator add/remove buttons on work landing pages.
"""

import json

from django.contrib.auth import get_user_model
from django.contrib.gis.geos import GeometryCollection, Point
from django.test import TestCase, Client
from django.urls import reverse

from works.models import Collection, Source, Work
from works.utils.provenance import append_event

User = get_user_model()


class CollectionModelTests(TestCase):
    def test_get_absolute_url_uses_identifier(self):
        col = Collection.objects.create(identifier='mountain-wetlands', name='Mountain Wetlands')
        self.assertEqual(col.get_absolute_url(), '/collections/mountain-wetlands/')


class CollectionsIndexTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.published = Collection.objects.create(
            identifier='public', name='Public', is_published=True,
        )
        self.unpublished = Collection.objects.create(
            identifier='hidden', name='Hidden', is_published=False,
        )
        self.admin = User.objects.create_user(
            username='admin@example.com', email='admin@example.com',
            password='admin123', is_staff=True, is_superuser=True,
        )

    def test_anonymous_sees_only_published(self):
        resp = self.client.get(reverse('optimap:collections'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Public')
        self.assertNotContains(resp, 'Hidden')

    def test_admin_sees_all_with_inline_controls(self):
        self.client.login(username='admin@example.com', password='admin123')
        resp = self.client.get(reverse('optimap:collections'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Public')
        self.assertContains(resp, 'Hidden')
        self.assertContains(resp, 'collection-publish-btn')   # button on Hidden
        self.assertContains(resp, 'collection-unpublish-btn') # button on Public


class CollectionDetailPageTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.col = Collection.objects.create(
            identifier='mw', name='MW Repo', is_published=True,
        )
        self.source = Source.objects.create(
            name='MW Source', url_field='https://example.com/api',
            source_type='mountain-wetlands',
        )
        self.work = Work.objects.create(
            title='A study', status='p',
            doi='10.1234/mw1',
            geometry=GeometryCollection(Point(-69.22, -18.19)),
            source=self.source,
        )
        self.work.collections.add(self.col)

    def test_published_collection_renders_works(self):
        resp = self.client.get(reverse('optimap:collection-page', args=['mw']))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'A study')

    def test_collection_renders_coins_span_per_work(self):
        # Issue #243: per-item COinS spans let Zotero offer multi-item save.
        resp = self.client.get(reverse('optimap:collection-page', args=['mw']))
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        self.assertEqual(body.count('class="Z3988"'), 1)
        self.assertIn(f"rft_id=info%3Adoi%2F{self.work.doi.replace('/', '%2F')}", body)

    def test_card_links_to_optimap_landing_even_without_doi(self):
        # Issue: MaRESS works have no DOI and Work.url points at the JSON API,
        # so the card must always link to /work/<id>/ rather than the API URL.
        no_doi = Work.objects.create(
            title='A study without DOI', status='p',
            url='https://example.com/api/v1/items/42',
            geometry=GeometryCollection(Point(-1.0, 1.0)),
            source=self.source,
        )
        no_doi.collections.add(self.col)
        resp = self.client.get(reverse('optimap:collection-page', args=['mw']))
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        # Card title and "View work's page" button both link to /work/<id>/.
        self.assertEqual(body.count(f'href="/work/{no_doi.id}/"'), 2)
        # No card-level link to the external Work.url (it leaks into the map
        # GeoJSON properties — that's fine; we only care about visible card hrefs).
        self.assertNotIn('href="https://example.com/api/v1/items/42"', body)

    def test_unpublished_collection_404_for_anonymous(self):
        self.col.is_published = False
        self.col.save(update_fields=['is_published'])
        resp = self.client.get(reverse('optimap:collection-page', args=['mw']))
        self.assertEqual(resp.status_code, 404)


class CollectionDescriptionTests(TestCase):
    """Curator/admin can edit a collection's description inline; plain text only."""

    def setUp(self):
        self.client = Client()
        self.col = Collection.objects.create(
            identifier='c', name='C', is_published=True, description='Initial.',
        )
        self.curator = User.objects.create_user(
            username='c@x.com', email='c@x.com', password='p123',
        )
        self.col.curators.add(self.curator)
        self.outsider = User.objects.create_user(
            username='o@x.com', email='o@x.com', password='p123',
        )
        self.admin = User.objects.create_user(
            username='admin@x.com', email='admin@x.com', password='p123', is_staff=True,
        )

    def _post(self, description):
        return self.client.post(
            f'/collections/{self.col.id}/description/',
            data={'description': description},
        )

    def test_anonymous_cannot_edit(self):
        resp = self._post('hijacked')
        # @login_required redirects to login.
        self.assertEqual(resp.status_code, 302)
        self.col.refresh_from_db()
        self.assertEqual(self.col.description, 'Initial.')

    def test_outsider_cannot_edit(self):
        self.client.login(username='o@x.com', password='p123')
        resp = self._post('hijacked')
        self.assertEqual(resp.status_code, 403)
        self.col.refresh_from_db()
        self.assertEqual(self.col.description, 'Initial.')

    def test_curator_can_save(self):
        self.client.login(username='c@x.com', password='p123')
        resp = self._post('A new description.')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['success'], True)
        self.col.refresh_from_db()
        self.assertEqual(self.col.description, 'A new description.')

    def test_admin_can_save(self):
        self.client.login(username='admin@x.com', password='p123')
        resp = self._post('Admin edit.')
        self.assertEqual(resp.status_code, 200)
        self.col.refresh_from_db()
        self.assertEqual(self.col.description, 'Admin edit.')

    def test_html_is_stripped_on_save(self):
        # Plain text only — server-side strip_tags removes any HTML markup.
        self.client.login(username='c@x.com', password='p123')
        resp = self._post('Hello <script>alert(1)</script><b>world</b>')
        self.assertEqual(resp.status_code, 200)
        self.col.refresh_from_db()
        self.assertNotIn('<script>', self.col.description)
        self.assertNotIn('<b>', self.col.description)
        self.assertIn('Hello', self.col.description)
        self.assertIn('world', self.col.description)

    def test_curator_sees_editor_on_detail_page(self):
        self.client.login(username='c@x.com', password='p123')
        resp = self.client.get(reverse('optimap:collection-page', args=[self.col.identifier]))
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        self.assertIn('id="collection-description-form"', body)
        self.assertIn('id="collection-description-edit-btn"', body)

    def test_outsider_does_not_see_editor(self):
        self.client.login(username='o@x.com', password='p123')
        resp = self.client.get(reverse('optimap:collection-page', args=[self.col.identifier]))
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        self.assertNotIn('id="collection-description-form"', body)
        self.assertNotIn('id="collection-description-edit-btn"', body)

    def test_admin_sees_manage_curators_link(self):
        # Admin gets a one-click jump to the admin change page anchored on
        # the curators field — but curators don't, since they cannot manage
        # other curators.
        self.client.login(username='admin@x.com', password='p123')
        resp = self.client.get(reverse('optimap:collection-page', args=[self.col.identifier]))
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        self.assertIn(f'/admin/works/collection/{self.col.id}/change/#id_curators', body)
        self.assertIn('Manage curators', body)

    def test_curator_does_not_see_manage_curators_link(self):
        self.client.login(username='c@x.com', password='p123')
        resp = self.client.get(reverse('optimap:collection-page', args=[self.col.identifier]))
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        self.assertNotIn('Manage curators', body)
        self.assertNotIn('/admin/works/collection/', body)


class CollectionByIdRedirectTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.col = Collection.objects.create(identifier='mw', name='MW', is_published=True)
        self.unpublished = Collection.objects.create(identifier='hidden', name='Hidden', is_published=False)
        self.admin = User.objects.create_user(
            username='admin@example.com', email='admin@example.com',
            password='admin123', is_staff=True,
        )

    def test_id_url_redirects_to_canonical_slug(self):
        resp = self.client.get(f'/collections/{self.col.id}/')
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp['Location'], f'/collections/{self.col.identifier}/')

    def test_unknown_id_404(self):
        resp = self.client.get('/collections/9999999/')
        self.assertEqual(resp.status_code, 404)

    def test_unpublished_id_404_for_anonymous(self):
        resp = self.client.get(f'/collections/{self.unpublished.id}/')
        self.assertEqual(resp.status_code, 404)

    def test_unpublished_id_redirects_for_admin(self):
        self.client.login(username='admin@example.com', password='admin123')
        resp = self.client.get(f'/collections/{self.unpublished.id}/')
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp['Location'], f'/collections/{self.unpublished.identifier}/')


class VanityShortSlugRedirectTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.col = Collection.objects.create(
            identifier='agile-gi', short_slug='agile', name='AGILE', is_published=True,
        )

    def test_short_slug_301s_to_canonical(self):
        resp = self.client.get('/agile/')
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp['Location'], '/collections/agile-gi/')

    def test_unknown_short_slug_404(self):
        resp = self.client.get('/never-defined/')
        self.assertEqual(resp.status_code, 404)


class PublishUnpublishEndpointTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.col = Collection.objects.create(identifier='c1', name='C1', is_published=False)
        self.admin = User.objects.create_user(
            username='admin@example.com', email='admin@example.com',
            password='admin123', is_staff=True,
        )
        self.user = User.objects.create_user(
            username='user@example.com', email='user@example.com', password='user123',
        )

    def test_publish_requires_staff(self):
        self.client.login(username='user@example.com', password='user123')
        resp = self.client.post(f'/collections/{self.col.id}/publish/')
        # staff_member_required redirects non-staff
        self.assertEqual(resp.status_code, 302)
        self.col.refresh_from_db()
        self.assertFalse(self.col.is_published)

    def test_publish_then_unpublish(self):
        self.client.login(username='admin@example.com', password='admin123')

        resp = self.client.post(f'/collections/{self.col.id}/publish/')
        self.assertEqual(resp.status_code, 200)
        self.col.refresh_from_db()
        self.assertTrue(self.col.is_published)

        resp = self.client.post(f'/collections/{self.col.id}/unpublish/')
        self.assertEqual(resp.status_code, 200)
        self.col.refresh_from_db()
        self.assertFalse(self.col.is_published)


class CuratorAddRemoveTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.col = Collection.objects.create(identifier='c', name='C', is_published=True)
        self.curator = User.objects.create_user(
            username='c@x.com', email='c@x.com', password='p123',
        )
        self.col.curators.add(self.curator)
        self.outsider = User.objects.create_user(
            username='o@x.com', email='o@x.com', password='p123',
        )
        self.work = Work.objects.create(
            title='W', status='p', doi='10.1234/w',
            geometry=GeometryCollection(),
        )

    def test_outsider_cannot_add(self):
        self.client.login(username='o@x.com', password='p123')
        resp = self.client.post(f'/work/{self.work.id}/collection/{self.col.id}/add/')
        self.assertEqual(resp.status_code, 403)
        self.assertFalse(self.work.collections.filter(pk=self.col.pk).exists())

    def test_curator_can_add_and_remove(self):
        self.client.login(username='c@x.com', password='p123')
        resp = self.client.post(f'/work/{self.work.id}/collection/{self.col.id}/add/')
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(self.work.collections.filter(pk=self.col.pk).exists())

        resp = self.client.post(f'/work/{self.work.id}/collection/{self.col.id}/remove/')
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(self.work.collections.filter(pk=self.col.pk).exists())

    def test_work_can_belong_to_multiple_collections(self):
        """An article can be added to several collections; remove only drops one."""
        other = Collection.objects.create(identifier='c2', name='C2', is_published=True)
        other.curators.add(self.curator)
        self.client.login(username='c@x.com', password='p123')

        # Add to both — neither should displace the other.
        self.client.post(f'/work/{self.work.id}/collection/{self.col.id}/add/')
        self.client.post(f'/work/{self.work.id}/collection/{other.id}/add/')
        self.assertEqual(set(self.work.collections.values_list('pk', flat=True)), {self.col.pk, other.pk})

        # Removing from one leaves the work in the other.
        self.client.post(f'/work/{self.work.id}/collection/{self.col.id}/remove/')
        self.assertEqual(set(self.work.collections.values_list('pk', flat=True)), {other.pk})

    def test_add_is_idempotent(self):
        self.client.login(username='c@x.com', password='p123')
        self.client.post(f'/work/{self.work.id}/collection/{self.col.id}/add/')
        self.client.post(f'/work/{self.work.id}/collection/{self.col.id}/add/')
        self.assertEqual(self.work.collections.count(), 1)


class CollectionsSitemapTests(TestCase):
    def setUp(self):
        Collection.objects.create(identifier='a', name='A', is_published=True)
        Collection.objects.create(identifier='b', name='B', is_published=False)

    def test_only_published_in_sitemap(self):
        resp = self.client.get('/sitemap-collections.xml')
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        self.assertIn('/collections/a/', body)
        self.assertNotIn('/collections/b/', body)

    def test_collections_index_in_static_sitemap(self):
        resp = self.client.get('/sitemap-static.xml')
        self.assertEqual(resp.status_code, 200)
        self.assertIn('/collections/', resp.content.decode())


class ProvenanceHelperTests(TestCase):
    def test_append_event_creates_events_array(self):
        work = Work.objects.create(title='X', status='d', doi='10.1234/x',
                                   geometry=GeometryCollection())
        append_event(work, 'publish', user_id=1, user_email='admin@x.com',
                     status_from='c', status_to='p')
        work.save()
        work.refresh_from_db()
        events = work.provenance.get('events', [])
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]['type'], 'publish')
        self.assertEqual(events[0]['user_email'], 'admin@x.com')
        self.assertIn('at', events[0])

    def test_append_event_appends_to_existing_provenance(self):
        work = Work.objects.create(
            title='X', status='d', doi='10.1234/y',
            geometry=GeometryCollection(),
            provenance={'harvest': {'harvester': 'harvest_oai_endpoint'}, 'events': []},
        )
        append_event(work, 'contribution', user_id=2)
        append_event(work, 'publish', user_id=1)
        work.save()
        work.refresh_from_db()
        events = work.provenance.get('events', [])
        self.assertEqual([e['type'] for e in events], ['contribution', 'publish'])
        # Existing harvest section preserved.
        self.assertEqual(work.provenance['harvest']['harvester'], 'harvest_oai_endpoint')


class SourceCollectionPropagationTests(TestCase):
    """When ``Source.collection`` is set, every harvested Work is auto-added to it.

    The "no collection set" path on OAI-PMH sources no longer applies — the
    harvester's entry point (``harvest_oai_endpoint``) always calls
    ``ensure_collection_for_source`` first, see
    ``tests/test_oai_collection_auto_create.py``. Source types that aren't
    auto-created (``rss``, ``crossref-prefix``, ``mountain-wetlands``) get
    their Collection from ``harvest_journals --insert-sources``.
    """

    def setUp(self):
        from pathlib import Path
        from works.models import HarvestingEvent
        from works.tasks import parse_oai_xml_and_save_works

        self.parse_oai = parse_oai_xml_and_save_works
        self.xml_bytes = (
            Path(__file__).resolve().parent / 'harvesting' / 'source_1' / 'oai_dc.xml'
        ).read_bytes()
        self.event_cls = HarvestingEvent

    def test_source_collection_propagates_to_harvested_works(self):
        col = Collection.objects.create(identifier='auto', name='Auto', is_published=True)
        src = Source.objects.create(name='S2', url_field='https://example.com/oai', collection=col)
        event = self.event_cls.objects.create(source=src, status='in_progress')

        self.parse_oai(self.xml_bytes, event)

        works = list(Work.objects.filter(job=event))
        self.assertGreater(len(works), 0)
        for w in works:
            self.assertIn(col, list(w.collections.all()),
                          f'work {w.pk} should have been added to the source collection')


class SourceSourceTypeAndScheduleTests(TestCase):
    def test_default_source_type_is_oai_pmh(self):
        s = Source.objects.create(name='S', url_field='https://example.com/oai')
        self.assertEqual(s.source_type, 'oai-pmh')

    def test_default_interval_is_zero(self):
        # Source.objects.create overrides — but the field default applies when
        # callers omit the kwarg.
        s = Source.objects.create(name='S2', url_field='https://example.com/oai')
        self.assertEqual(s.harvest_interval_minutes, 0)

    def test_zero_interval_does_not_create_schedule(self):
        from django_q.models import Schedule
        s = Source.objects.create(name='S3', url_field='https://example.com/oai',
                                  source_type='oai-pmh')
        self.assertFalse(Schedule.objects.filter(name=f'Harvest Source {s.id}').exists())

    def test_save_dispatches_to_correct_task_for_rss(self):
        from django_q.models import Schedule
        s = Source.objects.create(
            name='S4', url_field='https://example.com/feed.rss',
            source_type='rss', harvest_interval_minutes=60,
        )
        sched = Schedule.objects.get(name=f'Harvest Source {s.id}')
        self.assertEqual(sched.func, 'works.tasks.harvest_rss_endpoint')
