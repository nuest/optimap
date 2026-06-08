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

    def test_admin_response_is_not_cached_by_middleware(self):
        # Site-wide UpdateCacheMiddleware would otherwise cache this response,
        # so an admin's view would not reflect publish/unpublish actions until
        # the entry expired. Regression for the production bug where the
        # button state did not flip after a successful POST.
        self.client.login(username='admin@example.com', password='admin123')
        resp = self.client.get(reverse('optimap:collections'))
        cache_control = resp.headers.get('Cache-Control', '')
        self.assertIn('no-cache', cache_control)
        self.assertIn('no-store', cache_control)


class CollectionsIndexCountsTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.col = Collection.objects.create(
            identifier='mixed', name='Mixed', is_published=True,
        )
        self.other = Collection.objects.create(
            identifier='other', name='Other', is_published=True,
        )
        for i in range(2):
            Work.objects.create(
                title=f'pub-{i}', status='p', doi=f'10.1234/p{i}',
                geometry=GeometryCollection(Point(0, 0)),
            ).collections.add(self.col)
        for i in range(3):
            Work.objects.create(
                title=f'harv-{i}', status='h', doi=f'10.1234/h{i}',
                geometry=GeometryCollection(Point(0, 0)),
            ).collections.add(self.col)
        Work.objects.create(
            title='contrib', status='c', doi='10.1234/contrib',
            geometry=GeometryCollection(Point(0, 0)),
        ).collections.add(self.col)
        Work.objects.create(
            title='other-pub', status='p', doi='10.1234/other',
            geometry=GeometryCollection(Point(0, 0)),
        ).collections.add(self.other)

    def test_anonymous_sees_only_published_count(self):
        resp = self.client.get(reverse('optimap:collections'))
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        self.assertIn('2 works', body)
        self.assertNotIn('Harvested:', body)
        self.assertNotIn('Contributed:', body)
        self.assertNotIn('6 works', body)

    def test_authenticated_non_curator_sees_only_published_count(self):
        outsider = User.objects.create_user(
            username='outsider@example.com', email='outsider@example.com', password='p',
        )
        self.client.force_login(outsider)
        resp = self.client.get(reverse('optimap:collections'))
        body = resp.content.decode()
        self.assertIn('2 works', body)
        self.assertNotIn('Harvested:', body)
        self.assertNotIn('Contributed:', body)

    def test_admin_sees_per_status_breakdown(self):
        admin = User.objects.create_user(
            username='admin-counts@example.com', email='admin-counts@example.com',
            password='p', is_staff=True,
        )
        self.client.force_login(admin)
        resp = self.client.get(reverse('optimap:collections'))
        body = resp.content.decode()
        self.assertIn('Published: 2', body)
        self.assertIn('Harvested: 3', body)
        self.assertIn('Contributed: 1', body)
        self.assertNotIn('Draft:', body)
        self.assertNotIn('Testing:', body)
        self.assertNotIn('Withdrawn:', body)

    def test_curator_sees_breakdown_only_for_curated_collection(self):
        curator = User.objects.create_user(
            username='cur@example.com', email='cur@example.com', password='p',
        )
        self.col.curators.add(curator)
        self.client.force_login(curator)
        resp = self.client.get(reverse('optimap:collections'))
        body = resp.content.decode()
        self.assertIn('Published: 2', body)
        self.assertIn('Harvested: 3', body)
        self.assertIn('Contributed: 1', body)
        self.assertIn('1 work', body)


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

    def test_curator_sees_unpublished_works_and_status_badge(self):
        # Add a non-published work so we can verify (a) it is rendered for
        # curators / admins (visibility expansion) and (b) its publication
        # status badge is shown in the work card.
        draft = Work.objects.create(
            title='A draft study', status='d',
            doi='10.1234/mw-draft',
            geometry=GeometryCollection(Point(-70.0, -19.0)),
            source=self.source,
        )
        draft.collections.add(self.col)

        # Anonymous: draft not visible, no status badge for the published work.
        anon = self.client.get(reverse('optimap:collection-page', args=['mw']))
        self.assertEqual(anon.status_code, 200)
        anon_body = anon.content.decode()
        self.assertNotIn('A draft study', anon_body)
        self.assertNotIn('badge-secondary', anon_body)  # no Draft badge for anon

        # Curator: draft visible + Draft badge rendered.
        curator = User.objects.create_user(
            username='curator@example.com', email='curator@example.com', password='x',
        )
        self.col.curators.add(curator)
        self.client.force_login(curator)
        resp = self.client.get(reverse('optimap:collection-page', args=['mw']))
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        self.assertIn('A draft study', body)
        self.assertIn('badge-secondary', body)
        self.assertIn('Draft', body)
        # The published work should NOT carry a "not visible to anonymous users"
        # caveat next to its badge.
        self.assertIn('badge-success', body)
        # Curators do see the caveat next to non-published works.
        self.assertIn('not visible to anonymous users', body)

    def test_admin_sees_status_badges(self):
        admin = User.objects.create_user(
            username='a@b.c', email='a@b.c', password='x', is_staff=True,
        )
        self.client.force_login(admin)
        resp = self.client.get(reverse('optimap:collection-page', args=['mw']))
        self.assertEqual(resp.status_code, 200)
        # Published work in setUp gets the green badge for admin.
        self.assertIn('badge-success', resp.content.decode())

    def test_curator_response_is_not_cached_by_middleware(self):
        # Same regression as the index page: curator/admin responses must
        # bypass the site-wide cache so inline-mutation state stays live.
        admin = User.objects.create_user(
            username='admin-cache@example.com', email='admin-cache@example.com',
            password='x', is_staff=True,
        )
        self.client.force_login(admin)
        resp = self.client.get(reverse('optimap:collection-page', args=['mw']))
        cache_control = resp.headers.get('Cache-Control', '')
        self.assertIn('no-cache', cache_control)
        self.assertIn('no-store', cache_control)

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

    def test_admin_sees_inline_curator_ui(self):
        # Admin sees the inline add/remove curator form; the old Django Admin
        # "Manage curators" anchored link was replaced by this in-page UI.
        self.client.login(username='admin@x.com', password='p123')
        resp = self.client.get(reverse('optimap:collection-page', args=[self.col.identifier]))
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        self.assertIn('add-curator-form', body)
        self.assertNotIn('#id_curators', body)

    def test_curator_sees_inline_curator_ui(self):
        self.client.login(username='c@x.com', password='p123')
        resp = self.client.get(reverse('optimap:collection-page', args=[self.col.identifier]))
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        self.assertIn('add-curator-form', body)


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


class PublishCollectionWorksTests(TestCase):
    """Admin-only bulk action to flip Harvested/Contributed works to Published.

    Curators (non-staff) must be rejected — explicitly tested because curators
    can otherwise edit collection descriptions and add/remove individual works.
    """

    def setUp(self):
        self.client = Client()
        self.col = Collection.objects.create(identifier='c', name='C', is_published=True)
        self.admin = User.objects.create_user(
            username='admin@x.com', email='admin@x.com', password='p123', is_staff=True,
        )
        self.curator = User.objects.create_user(
            username='c@x.com', email='c@x.com', password='p123',
        )
        self.col.curators.add(self.curator)

        self.harvested = Work.objects.create(
            title='H', status='h', doi='10.1234/h',
            geometry=GeometryCollection(Point(0, 0)),
        )
        self.contributed = Work.objects.create(
            title='C', status='c', doi='10.1234/c',
            geometry=GeometryCollection(Point(1, 1)),
        )
        self.draft = Work.objects.create(
            title='D', status='d', doi='10.1234/d',
            geometry=GeometryCollection(Point(2, 2)),
        )
        self.withdrawn = Work.objects.create(
            title='W', status='w', doi='10.1234/w',
            geometry=GeometryCollection(Point(3, 3)),
        )
        self.already_published = Work.objects.create(
            title='P', status='p', doi='10.1234/p',
            geometry=GeometryCollection(Point(4, 4)),
        )
        for w in (self.harvested, self.contributed, self.draft, self.withdrawn, self.already_published):
            w.collections.add(self.col)

        # Work in another collection — must not be touched.
        self.other_col = Collection.objects.create(identifier='other', name='Other', is_published=True)
        self.outsider_work = Work.objects.create(
            title='O', status='h', doi='10.1234/o',
            geometry=GeometryCollection(Point(5, 5)),
        )
        self.outsider_work.collections.add(self.other_col)

    def _url(self):
        return f'/collections/{self.col.id}/publish-works/'

    def test_admin_publishes_harvested_and_contributed_only(self):
        self.client.force_login(self.admin)
        resp = self.client.post(self._url())
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {'success': True, 'published_count': 2})

        for w in (self.harvested, self.contributed):
            w.refresh_from_db()
            self.assertEqual(w.status, 'p')
        # Draft / Withdrawn deliberately untouched.
        self.draft.refresh_from_db()
        self.assertEqual(self.draft.status, 'd')
        self.withdrawn.refresh_from_db()
        self.assertEqual(self.withdrawn.status, 'w')
        # Other collection's work untouched.
        self.outsider_work.refresh_from_db()
        self.assertEqual(self.outsider_work.status, 'h')

    def test_curator_is_rejected(self):
        self.client.force_login(self.curator)
        resp = self.client.post(self._url())
        # staff_member_required redirects to admin login for non-staff.
        self.assertEqual(resp.status_code, 302)
        self.harvested.refresh_from_db()
        self.assertEqual(self.harvested.status, 'h')

    def test_anonymous_is_rejected(self):
        resp = self.client.post(self._url())
        self.assertEqual(resp.status_code, 302)
        self.harvested.refresh_from_db()
        self.assertEqual(self.harvested.status, 'h')

    def test_get_is_not_allowed(self):
        self.client.force_login(self.admin)
        resp = self.client.get(self._url())
        self.assertEqual(resp.status_code, 405)

    def test_button_visible_to_admin_with_count(self):
        self.client.force_login(self.admin)
        resp = self.client.get(reverse('optimap:collection-page', args=[self.col.identifier]))
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        self.assertIn('collection-publish-works-btn', body)
        # 2 works are h/c, count rendered in the button label.
        self.assertIn('Publish all 2 unpublished works', body)

    def test_button_hidden_when_no_publishable_works(self):
        # Flip the two candidates to Published — button disappears. The class
        # name and ``data-publishable-count`` both appear in the admin's JS
        # handler block, so assert on the human-visible label that only the
        # rendered button carries.
        self.harvested.status = 'p'; self.harvested.save()
        self.contributed.status = 'p'; self.contributed.save()
        self.client.force_login(self.admin)
        resp = self.client.get(reverse('optimap:collection-page', args=[self.col.identifier]))
        self.assertNotIn('Publish all', resp.content.decode())

    def test_button_hidden_for_curator(self):
        self.client.force_login(self.curator)
        resp = self.client.get(reverse('optimap:collection-page', args=[self.col.identifier]))
        self.assertNotIn('Publish all', resp.content.decode())


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


class WorkLandingPageCollectionBacklinksTests(TestCase):
    """Work landing pages link back to the collections the work belongs to."""

    def setUp(self):
        self.client = Client()
        self.published_a = Collection.objects.create(
            identifier='pub-a', name='Pub A', is_published=True,
        )
        self.published_b = Collection.objects.create(
            identifier='pub-b', name='Pub B', is_published=True,
        )
        self.hidden = Collection.objects.create(
            identifier='hidden-c', name='Hidden C', is_published=False,
        )
        self.work = Work.objects.create(
            title='W', status='p', doi='10.1234/wbacklinks',
            geometry=GeometryCollection(Point(0, 0)),
        )
        self.work.collections.add(self.published_a, self.published_b, self.hidden)
        self.admin = User.objects.create_user(
            username='admin@x.com', email='admin@x.com', password='p123', is_staff=True,
        )

    def _landing_url(self):
        return reverse('optimap:work-landing', args=[self.work.get_identifier()])

    def test_anonymous_sees_only_published_collections(self):
        resp = self.client.get(self._landing_url())
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        self.assertIn('id="work-collections"', body)
        self.assertIn(f'href="/collections/{self.published_a.identifier}/"', body)
        self.assertIn(f'href="/collections/{self.published_b.identifier}/"', body)
        # Unpublished collection backlink hidden from the public.
        self.assertNotIn(f'href="/collections/{self.hidden.identifier}/"', body)
        self.assertNotIn('Hidden C', body)

    def test_admin_also_sees_unpublished_collections(self):
        self.client.login(username='admin@x.com', password='p123')
        resp = self.client.get(self._landing_url())
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        self.assertIn(f'href="/collections/{self.hidden.identifier}/"', body)
        # Tagged as unpublished so admins can tell them apart.
        self.assertIn('unpublished', body)

    def test_no_backlinks_block_when_work_has_no_collections(self):
        lonely = Work.objects.create(
            title='Lonely', status='p', doi='10.1234/lonely',
            geometry=GeometryCollection(),
        )
        url = reverse('optimap:work-landing', args=[lonely.get_identifier()])
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        self.assertNotIn('id="work-collections"', body)


class ContributeCollectionFilterTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.col = Collection.objects.create(
            identifier='mw', short_slug='mw-vanity', name='Mountain Wetlands',
            is_published=True,
        )
        self.other = Collection.objects.create(
            identifier='other', name='Other', is_published=True,
        )
        self.hidden = Collection.objects.create(
            identifier='hidden', name='Hidden Stuff', is_published=False,
        )
        self.mw_needs = Work.objects.create(
            title='MW needs geom', status='h', doi='10.1234/mw-need',
        )
        self.mw_needs.collections.add(self.col)
        self.mw_done = Work.objects.create(
            title='MW already published', status='p', doi='10.1234/mw-done',
            geometry=GeometryCollection(Point(0, 0)),
        )
        self.mw_done.collections.add(self.col)
        self.other_needs = Work.objects.create(
            title='Other needs geom', status='h', doi='10.1234/other-need',
        )
        self.other_needs.collections.add(self.other)
        self.loose_needs = Work.objects.create(
            title='Loose needs geom', status='h', doi='10.1234/loose-need',
        )

    def test_no_filter_shows_all_harvested(self):
        resp = self.client.get(reverse('optimap:contribute'))
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        self.assertIn('MW needs geom', body)
        self.assertIn('Other needs geom', body)
        self.assertIn('Loose needs geom', body)
        self.assertNotIn('Filtered to collection', body)

    def test_filter_by_identifier(self):
        resp = self.client.get(reverse('optimap:contribute') + '?collection=mw')
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        self.assertIn('MW needs geom', body)
        self.assertNotIn('Other needs geom', body)
        self.assertNotIn('Loose needs geom', body)
        self.assertIn('Filtered to collection', body)
        self.assertIn('Mountain Wetlands', body)
        self.assertIn('Show all', body)

    def test_filter_by_numeric_id(self):
        resp = self.client.get(reverse('optimap:contribute') + f'?collection={self.col.id}')
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        self.assertIn('MW needs geom', body)
        self.assertNotIn('Other needs geom', body)
        self.assertIn('Mountain Wetlands', body)

    def test_filter_by_short_slug(self):
        resp = self.client.get(reverse('optimap:contribute') + '?collection=mw-vanity')
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        self.assertIn('MW needs geom', body)
        self.assertNotIn('Other needs geom', body)

    def test_unknown_filter_shows_all_with_warning(self):
        resp = self.client.get(reverse('optimap:contribute') + '?collection=nope')
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        self.assertIn('Unknown collection', body)
        self.assertIn('MW needs geom', body)
        self.assertIn('Other needs geom', body)
        self.assertIn('Loose needs geom', body)

    def test_unpublished_collection_hidden_from_anonymous(self):
        resp = self.client.get(reverse('optimap:contribute') + '?collection=hidden')
        body = resp.content.decode()
        self.assertIn('Unknown collection', body)
        self.assertNotIn('Hidden Stuff', body)

    def test_unpublished_collection_filterable_by_admin(self):
        admin = User.objects.create_user(
            username='ad@example.com', email='ad@example.com', password='p', is_staff=True,
        )
        w = Work.objects.create(title='Hidden harvest', status='h', doi='10.1234/hh')
        w.collections.add(self.hidden)
        self.client.force_login(admin)
        resp = self.client.get(reverse('optimap:contribute') + '?collection=hidden')
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        self.assertIn('Hidden Stuff', body)
        self.assertIn('Hidden harvest', body)
        self.assertNotIn('Other needs geom', body)


class CollectionPageContributeLinkTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.col = Collection.objects.create(
            identifier='mw', name='Mountain Wetlands', is_published=True,
        )

    def test_link_present_on_collection_page(self):
        resp = self.client.get(reverse('optimap:collection-page', args=['mw']))
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        self.assertIn('/contribute/?collection=mw', body)
        self.assertIn('Contribute metadata for this collection', body)


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


class CollectionCuratorManagementTests(TestCase):
    """Tests for the inline add/remove curator endpoints on the collection page."""

    def setUp(self):
        self.client = Client()
        self.col = Collection.objects.create(
            identifier='test-col', name='Test Collection', is_published=True,
        )
        self.admin = User.objects.create_user(
            username='admin@example.com', email='admin@example.com',
            password='admin123', is_staff=True,
        )
        self.curator = User.objects.create_user(
            username='curator@example.com', email='curator@example.com', password='c',
        )
        self.col.curators.add(self.curator)
        self.other_user = User.objects.create_user(
            username='other@example.com', email='other@example.com', password='o',
        )
        self.add_url = reverse('optimap:collection-add-curator', args=[self.col.id])
        self.remove_url = reverse('optimap:collection-remove-curator',
                                  args=[self.col.id, self.curator.id])

    # --- add_curator ---

    def test_admin_can_add_curator(self):
        self.client.force_login(self.admin)
        resp = self.client.post(self.add_url, {'email': self.other_user.email})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data['success'])
        self.assertIn(self.other_user, self.col.curators.all())

    def test_existing_curator_can_add_another_curator(self):
        self.client.force_login(self.curator)
        resp = self.client.post(self.add_url, {'email': self.other_user.email})
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()['success'])
        self.assertIn(self.other_user, self.col.curators.all())

    def test_non_curator_gets_403(self):
        self.client.force_login(self.other_user)
        resp = self.client.post(self.add_url, {'email': self.admin.email})
        self.assertEqual(resp.status_code, 403)
        self.assertNotIn(self.admin, self.col.curators.all())

    def test_anonymous_redirected(self):
        resp = self.client.post(self.add_url, {'email': self.other_user.email})
        self.assertEqual(resp.status_code, 302)

    def test_unknown_email_returns_404(self):
        self.client.force_login(self.admin)
        resp = self.client.post(self.add_url, {'email': 'nobody@nowhere.example'})
        self.assertEqual(resp.status_code, 404)
        data = resp.json()
        self.assertIn('error', data)

    def test_add_already_curator_is_idempotent(self):
        self.client.force_login(self.admin)
        resp = self.client.post(self.add_url, {'email': self.curator.email})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data['success'])
        self.assertTrue(data.get('already_curator'))
        self.assertEqual(self.col.curators.count(), 1)

    def test_missing_email_returns_400(self):
        self.client.force_login(self.admin)
        resp = self.client.post(self.add_url, {})
        self.assertEqual(resp.status_code, 400)

    def test_notification_queued_on_add(self):
        from unittest.mock import patch
        self.client.force_login(self.admin)
        with patch('django_q.tasks.async_task') as mock_task:
            self.client.post(self.add_url, {'email': self.other_user.email})
        mock_task.assert_called_once()
        args = mock_task.call_args[0]
        self.assertEqual(args[0], 'works.notifications.send_curator_change_email')
        self.assertEqual(args[3], self.other_user.pk)   # changed_user_id
        self.assertEqual(args[4], 'added')

    # --- remove_curator ---

    def test_admin_can_remove_curator(self):
        self.client.force_login(self.admin)
        resp = self.client.post(self.remove_url)
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()['success'])
        self.assertNotIn(self.curator, self.col.curators.all())

    def test_curator_can_remove_another_curator(self):
        extra = User.objects.create_user(
            username='extra@example.com', email='extra@example.com', password='e',
        )
        self.col.curators.add(extra)
        url = reverse('optimap:collection-remove-curator', args=[self.col.id, extra.id])
        self.client.force_login(self.curator)
        resp = self.client.post(url)
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()['success'])
        self.assertNotIn(extra, self.col.curators.all())

    def test_non_curator_cannot_remove_curator(self):
        self.client.force_login(self.other_user)
        resp = self.client.post(self.remove_url)
        self.assertEqual(resp.status_code, 403)
        self.assertIn(self.curator, self.col.curators.all())

    def test_remove_non_curator_returns_400(self):
        self.client.force_login(self.admin)
        url = reverse('optimap:collection-remove-curator',
                      args=[self.col.id, self.other_user.id])
        resp = self.client.post(url)
        self.assertEqual(resp.status_code, 400)

    def test_notification_queued_on_remove(self):
        from unittest.mock import patch
        self.client.force_login(self.admin)
        with patch('django_q.tasks.async_task') as mock_task:
            self.client.post(self.remove_url)
        mock_task.assert_called_once()
        args = mock_task.call_args[0]
        self.assertEqual(args[0], 'works.notifications.send_curator_change_email')
        self.assertEqual(args[3], self.curator.pk)   # changed_user_id
        self.assertEqual(args[4], 'removed')

    # --- curator UI visible on collection page ---

    def test_curator_section_shown_for_admin(self):
        self.client.force_login(self.admin)
        resp = self.client.get(reverse('optimap:collection-page', args=['test-col']))
        self.assertContains(resp, 'add-curator-form')
        self.assertContains(resp, 'curator-remove-btn')

    def test_curator_section_shown_for_curator(self):
        self.client.force_login(self.curator)
        resp = self.client.get(reverse('optimap:collection-page', args=['test-col']))
        self.assertContains(resp, 'add-curator-form')

    def test_curator_section_hidden_for_anonymous(self):
        resp = self.client.get(reverse('optimap:collection-page', args=['test-col']))
        self.assertNotContains(resp, 'add-curator-form')


class SourceCollectionPropagationTests(TestCase):
    """When ``Source.collection`` is set, every harvested Work is auto-added to it.

    The "no collection set" path on OAI-PMH sources no longer applies — the
    harvester's entry point (``harvest_oai_endpoint``) always calls
    ``ensure_collection_for_source`` first, see
    ``tests/test_oai_collection_auto_create.py``. Source types that aren't
    auto-created (``rss``, ``crossref-prefix``, ``mountain-wetlands``) get
    their Collection from ``harvest_sources --insert-sources``.
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


class ProvenanceEndpointTests(TestCase):
    """Tests for GET /api/v1/works/<id>/provenance/."""

    FULL_PROVENANCE = {
        "harvest": {
            "harvester": "harvest_oai_endpoint",
            "source_name": "Test Journal",
            "source_type": "oai-pmh",
            "source_url": "https://example.com/oai",
            "harvested_at": "2026-01-01T12:00:00+00:00",
            "harvesting_event_id": 99,
            "doi": "10.1234/test",
            "original_record": {"identifier": "oai:example.com:1"},
        },
        "metadata_sources": {"authors": "openalex", "geometry": "DC.SpatialCoverage"},
        "openalex_match": {
            "status": "verified",
            "score": 0.95,
            "matched_id": "https://openalex.org/W999",
            "top_candidate": {"id": "W999", "title": "raw payload"},
        },
        "events": [
            {"type": "harvest", "at": "2026-01-01T12:00:00+00:00"},
            {"type": "contribution", "at": "2026-01-02T10:00:00+00:00",
             "user_id": 42, "kind": "spatial"},
            {"type": "publish", "at": "2026-01-03T09:00:00+00:00", "user_id": 1},
        ],
    }

    def setUp(self):
        self.client = Client()
        self.collection = Collection.objects.create(
            identifier='test-col', name='Test Collection', is_published=True,
        )
        self.other_collection = Collection.objects.create(
            identifier='other-col', name='Other Collection', is_published=True,
        )
        self.staff = User.objects.create_user(
            username='staff@example.com', email='staff@example.com',
            password='pw', is_staff=True,
        )
        self.curator = User.objects.create_user(
            username='curator@example.com', email='curator@example.com', password='pw',
        )
        self.collection.curators.add(self.curator)
        self.other_curator = User.objects.create_user(
            username='othercurator@example.com', email='othercurator@example.com', password='pw',
        )
        self.other_collection.curators.add(self.other_curator)
        self.regular = User.objects.create_user(
            username='user@example.com', email='user@example.com', password='pw',
        )
        self.published_work = Work.objects.create(
            title='Published', status='p', doi='10.1234/pub',
            provenance=self.FULL_PROVENANCE,
        )
        self.published_work.collections.add(self.collection)
        self.draft_work = Work.objects.create(
            title='Draft', status='d', doi='10.1234/draft',
            provenance=self.FULL_PROVENANCE,
        )
        self.draft_work.collections.add(self.collection)

    def _url(self, work):
        return f'/api/v1/works/{work.id}/provenance/'

    # --- anonymous access ---

    def test_anonymous_published_returns_public_subset(self):
        resp = self.client.get(self._url(self.published_work))
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        # public fields present
        self.assertIn('harvested_at', data['harvest'])
        self.assertIn('metadata_sources', data)
        self.assertIn('openalex_match', data)
        # private keys absent
        self.assertNotIn('original_record', data.get('harvest', {}))
        self.assertNotIn('top_candidate', data.get('openalex_match', {}))
        for ev in data.get('events', []):
            self.assertNotIn('user_id', ev)

    def test_anonymous_published_cache_header_is_public(self):
        resp = self.client.get(self._url(self.published_work))
        self.assertIn('public', resp.get('Cache-Control', ''))

    def test_anonymous_draft_returns_404(self):
        resp = self.client.get(self._url(self.draft_work))
        self.assertEqual(resp.status_code, 404)

    def test_anonymous_empty_provenance_returns_empty_dict(self):
        work = Work.objects.create(title='Empty', status='p', doi='10.1234/empty', provenance={})
        resp = self.client.get(self._url(work))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {})

    # --- staff access ---

    def test_staff_published_returns_full_provenance(self):
        self.client.force_login(self.staff)
        resp = self.client.get(self._url(self.published_work))
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn('original_record', data['harvest'])
        self.assertIn('top_candidate', data['openalex_match'])
        # user_id must survive for staff
        contribution_events = [e for e in data.get('events', []) if e.get('type') == 'contribution']
        self.assertTrue(any('user_id' in e for e in contribution_events))

    def test_staff_draft_returns_full_provenance(self):
        self.client.force_login(self.staff)
        resp = self.client.get(self._url(self.draft_work))
        self.assertEqual(resp.status_code, 200)
        self.assertIn('original_record', resp.json()['harvest'])

    def test_staff_cache_header_is_private_no_store(self):
        self.client.force_login(self.staff)
        resp = self.client.get(self._url(self.published_work))
        cc = resp.get('Cache-Control', '')
        self.assertIn('private', cc)
        self.assertIn('no-store', cc)

    # --- curator access ---

    def test_curator_of_works_collection_gets_full_provenance(self):
        self.client.force_login(self.curator)
        resp = self.client.get(self._url(self.published_work))
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn('original_record', data['harvest'])
        self.assertIn('top_candidate', data['openalex_match'])

    def test_curator_of_works_collection_can_access_draft(self):
        self.client.force_login(self.curator)
        resp = self.client.get(self._url(self.draft_work))
        self.assertEqual(resp.status_code, 200)
        self.assertIn('original_record', resp.json()['harvest'])

    def test_curator_of_different_collection_gets_public_subset(self):
        self.client.force_login(self.other_curator)
        resp = self.client.get(self._url(self.published_work))
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertNotIn('original_record', data.get('harvest', {}))
        self.assertNotIn('top_candidate', data.get('openalex_match', {}))

    def test_curator_of_different_collection_cannot_access_draft(self):
        self.client.force_login(self.other_curator)
        resp = self.client.get(self._url(self.draft_work))
        self.assertEqual(resp.status_code, 404)

    def test_regular_user_gets_public_subset(self):
        self.client.force_login(self.regular)
        resp = self.client.get(self._url(self.published_work))
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertNotIn('original_record', data.get('harvest', {}))
