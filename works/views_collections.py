# SPDX-FileCopyrightText: 2026 OPTIMETA and KOMET projects <https://projects.tib.eu/komet>
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Views for the curated /collections/ pages.

The detail page mirrors :func:`works.views_feeds.continent_feed_page` so the
two surfaces feel consistent (map + work cards). Inline admin/curator
controls render on the index and detail pages for staff users; they POST to
the small mutation endpoints below (publish/unpublish, add/remove a work).
"""

import json
import logging

from django.conf import settings
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import login_required
from django.http import Http404, JsonResponse, HttpResponseRedirect
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.html import strip_tags
from django.views.decorators.http import require_POST

from .models import Collection, Work
from .seo import coins_title
from .views_feeds import _publications_to_geojson

logger = logging.getLogger(__name__)


def _visible_collections(request):
    """Anonymous users see only published collections; staff see everything."""
    qs = Collection.objects.all().prefetch_related('curators').select_related()
    if not (request.user.is_authenticated and request.user.is_staff):
        qs = qs.filter(is_published=True)
    return qs


def _collection_for_request(request, collection_slug):
    """Resolve a collection by identifier, enforcing visibility."""
    try:
        collection = Collection.objects.get(identifier=collection_slug)
    except Collection.DoesNotExist:
        raise Http404(f"Collection not found: {collection_slug}")
    is_admin = request.user.is_authenticated and request.user.is_staff
    if not collection.is_published and not is_admin:
        raise Http404(f"Collection not found: {collection_slug}")
    return collection


def collections_index(request):
    """List all collections. Staff see unpublished too, with inline controls."""
    is_admin = request.user.is_authenticated and request.user.is_staff
    collections = list(_visible_collections(request))
    # Annotate with work count to avoid N+1 in templates.
    for c in collections:
        c.work_count = c.works.count()
    context = {
        'collections': collections,
        'is_admin': is_admin,
    }
    return render(request, 'collections.html', context)


def collection_page(request, collection_slug):
    """Detail page for one collection — map + work list + (for curators/admins) inline controls."""
    collection = _collection_for_request(request, collection_slug)
    is_admin = request.user.is_authenticated and request.user.is_staff
    is_curator = (
        request.user.is_authenticated
        and collection.curators.filter(pk=request.user.pk).exists()
    )

    # Visibility rule: anonymous / non-curators see only published works;
    # admins and curators of the collection see every work in the collection
    # so they can identify which ones still need review or publishing.
    can_curate = is_admin or is_curator
    works_qs = Work.objects.filter(collections=collection).select_related('source')
    if not can_curate:
        works_qs = works_qs.filter(status='p')
    works = list(works_qs.order_by('-creationDate', '-id')[: settings.FEED_MAX_ITEMS])
    for w in works:
        w.coins_ctx = coins_title(w)

    context = {
        'collection': collection,
        'works': works,
        'work_count_total': Work.objects.filter(collections=collection).count(),
        'publications_geojson': _publications_to_geojson(works),
        'is_admin': is_admin,
        'is_curator': is_curator,
        'can_curate': can_curate,
        'can_edit_description': is_admin or is_curator,
        'canonical_url': request.build_absolute_uri(collection.get_absolute_url()),
    }
    return render(request, 'collection_page.html', context)


def collection_short_redirect(request, short_slug):
    """Vanity-URL handler: ``/<short_slug>/`` → 301 to canonical ``/collections/<identifier>/``.

    Returns 404 when no Collection has this short_slug, so the URL only resolves
    for collections the admin has explicitly opted in.
    """
    try:
        collection = Collection.objects.get(short_slug=short_slug, is_published=True)
    except Collection.DoesNotExist:
        raise Http404(f"No collection with short slug {short_slug!r}")
    return HttpResponseRedirect(collection.get_absolute_url())


def collection_by_id_redirect(request, collection_id):
    """``/collections/<int:id>/`` → 301 to canonical ``/collections/<identifier>/``.

    Lets internal links / admin tools / external citations refer to a collection
    by its database ID without breaking when the identifier changes — but the
    canonical URL the user sees is always the slug. Same visibility rules as
    the slug page: unpublished collections 404 for anonymous users.
    """
    collection = get_object_or_404(Collection, pk=collection_id)
    is_admin = request.user.is_authenticated and request.user.is_staff
    if not collection.is_published and not is_admin:
        raise Http404(f"Collection not found: {collection_id}")
    return HttpResponseRedirect(collection.get_absolute_url())


# --- Mutation endpoints ----------------------------------------------------

@staff_member_required
@require_POST
def publish_collection(request, collection_id):
    collection = get_object_or_404(Collection, pk=collection_id)
    collection.is_published = True
    collection.save(update_fields=['is_published', 'updated_at'])
    return JsonResponse({'success': True, 'is_published': True})


@staff_member_required
@require_POST
def unpublish_collection(request, collection_id):
    collection = get_object_or_404(Collection, pk=collection_id)
    collection.is_published = False
    collection.save(update_fields=['is_published', 'updated_at'])
    return JsonResponse({'success': True, 'is_published': False})


def _user_can_curate(user, collection):
    """A user is a curator of X iff they're listed in collection.curators (or are staff)."""
    if not user.is_authenticated:
        return False
    if user.is_staff:
        return True
    return collection.curators.filter(pk=user.pk).exists()


@login_required
@require_POST
def update_collection_description(request, collection_id):
    """Curators (and staff) update a collection's description.

    Plain text only — incoming HTML is stripped server-side via
    ``strip_tags``, then re-saved. The Django template ``{{ description }}``
    auto-escapes on render, but stripping at write time also keeps the
    persisted value clean (e.g. for API/feed consumers).
    """
    collection = get_object_or_404(Collection, pk=collection_id)
    if not _user_can_curate(request.user, collection):
        return JsonResponse({'error': 'Not a curator of this collection.'}, status=403)
    raw = request.POST.get('description', '')
    cleaned = strip_tags(raw).strip()
    collection.description = cleaned
    collection.save(update_fields=['description', 'updated_at'])
    return JsonResponse({'success': True, 'description': cleaned})


@login_required
@require_POST
def add_work_to_collection(request, work_id, collection_id):
    """Curator adds a work to their collection. Idempotent — adding a work
    that's already in the collection is a no-op. A work can be in multiple
    collections, so this never displaces an existing membership."""
    work = get_object_or_404(Work, pk=work_id)
    collection = get_object_or_404(Collection, pk=collection_id)
    if not _user_can_curate(request.user, collection):
        return JsonResponse({'error': 'Not a curator of this collection.'}, status=403)
    work.collections.add(collection)
    return JsonResponse({
        'success': True,
        'work_id': work.id,
        'collection_id': collection.id,
        'collection_name': collection.name,
    })


@login_required
@require_POST
def remove_work_from_collection(request, work_id, collection_id):
    work = get_object_or_404(Work, pk=work_id)
    collection = get_object_or_404(Collection, pk=collection_id)
    if not _user_can_curate(request.user, collection):
        return JsonResponse({'error': 'Not a curator of this collection.'}, status=403)
    if not work.collections.filter(pk=collection.pk).exists():
        return JsonResponse({'error': 'Work is not in this collection.'}, status=400)
    work.collections.remove(collection)
    return JsonResponse({'success': True, 'work_id': work.id})
