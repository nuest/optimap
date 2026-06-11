# SPDX-FileCopyrightText: 2025 OPTIMETA and KOMET projects <https://projects.tib.eu/komet>
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Views for geometry contribution and work management.
"""
import logging
import json
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.admin.views.decorators import staff_member_required
from django.http import Http404, JsonResponse
from django.views.decorators.http import require_POST
from django.views.decorators.csrf import csrf_exempt
from django.contrib.gis.geos import GEOSGeometry
from django.utils import timezone
from works.models import Work, Contribution
from works.utils.identifiers import get_work_by_identifier
from works.utils.provenance import append_event, user_has_contributed_kind
from works.bok import client as bok_client

logger = logging.getLogger(__name__)


# Core ID-based views (internal implementation)

@require_POST
def contribute_geometry_by_id(request, work_id):
    """
    API endpoint for users to contribute geometry and/or temporal extent to a work by ID.
    Used for publications without a DOI.

    Open to logged-in users while a work is Harvested or Contributed. The
    first time a user contributes spatial/temporal/ontology to a work
    they get a Recognition Board row (deduped via the provenance log);
    repeated edits of the same property by the same user are recorded in
    provenance but do not double-count on the board. Pre-existing
    extents are not a barrier — replacing user A's geometry as user B is
    explicitly allowed, with the provenance log carrying attribution.
    """
    if not request.user.is_authenticated:
        return JsonResponse({'error': 'Authentication required'}, status=401)

    try:
        work = Work.objects.get(id=work_id)
    except Work.DoesNotExist:
        return JsonResponse({'error': 'Work not found'}, status=404)

    if work.status not in ('h', 'c'):
        return JsonResponse({
            'error': 'Can only contribute to harvested or contributed publications'
        }, status=400)

    try:
        data = json.loads(request.body)
        geojson = data.get('geometry')
        temporal_extent = data.get('temporal_extent')
        provenance_hint = data.get('provenance_hint')

        logger.info("Received contribution request for work ID: %s, data: %s", work_id, data)

        if not geojson and not temporal_extent:
            logger.warning("No geometry or temporal extent provided in request")
            return JsonResponse({'error': 'No geometry or temporal extent provided'}, status=400)

        changes_made = []
        spatial_contributed = False
        temporal_contributed = False

        if geojson:
            had_geometry = bool(work.geometry and not work.geometry.empty)
            logger.info("Converting geometry: %s", geojson)
            geometry = GEOSGeometry(json.dumps(geojson))
            work.geometry = geometry
            changes_made.append(
                f"{'Replaced geometry with' if had_geometry else 'Changed geometry from empty to'} "
                f"{geometry.geom_type}"
            )
            spatial_contributed = True

        if temporal_extent:
            start_date = temporal_extent.get('start_date')
            end_date = temporal_extent.get('end_date')

            if start_date:
                work.timeperiod_startdate = [start_date]
                changes_made.append(f"Set start date to {start_date}")
                temporal_contributed = True
            if end_date:
                work.timeperiod_enddate = [end_date]
                changes_made.append(f"Set end date to {end_date}")
                temporal_contributed = True

        # Recognition Board dedup decisions taken BEFORE we record this
        # event, so the new event doesn't count against itself.
        record_spatial_row = (
            spatial_contributed
            and not user_has_contributed_kind(work, request.user.id, "spatial")
        )
        record_temporal_row = (
            temporal_contributed
            and not user_has_contributed_kind(work, request.user.id, "temporal")
        )

        status_from = work.status
        # Harvested works flip to Contributed on the first contribution;
        # already-Contributed works stay there.
        status_to = 'c'

        append_event(
            work,
            "contribution",
            user_id=request.user.id,
            user_email=request.user.email,
            kinds=[k for k, flag in (("spatial", spatial_contributed), ("temporal", temporal_contributed)) if flag],
            changes=changes_made,
            status_from=status_from,
            status_to=status_to,
            geometry_source=provenance_hint if isinstance(provenance_hint, dict) else None,
        )
        work.status = status_to
        work.save()

        if record_spatial_row:
            Contribution.objects.create(user=request.user, work=work, kind=Contribution.SPATIAL)
        if record_temporal_row:
            Contribution.objects.create(user=request.user, work=work, kind=Contribution.TEMPORAL)

        logger.info(
            "User %s contributed to work %s (ID: %s): %s",
            request.user.username, work.title[:50], work.id, ", ".join(changes_made)
        )

        from works.notifications import notify_work_event
        notify_work_event(work, "contribution", actor=request.user)

        messages.success(
            request,
            "Thank you for your contribution! It is now visible to curators and admins for review.",
        )

        return JsonResponse({
            'success': True,
            'message': 'Thank you for your contribution! '
                      'An administrator will review your changes.'
        })

    except json.JSONDecodeError as e:
        logger.error("JSON decode error: %s", str(e))
        return JsonResponse({'error': 'Invalid JSON'}, status=400)
    except Exception as e:
        logger.error("Error saving contribution: %s", str(e), exc_info=True)
        return JsonResponse({'error': str(e)}, status=500)


@staff_member_required
@require_POST
def publish_work_by_id(request, work_id):
    """
    API endpoint for admins to publish a work by ID.
    Used for publications without a DOI.
    Changes status from 'Contributed' or 'Harvested' to 'Published'.
    For harvested publications, requires that at least one extent (spatial or temporal) exists.
    """
    try:
        work = Work.objects.get(id=work_id)
    except Work.DoesNotExist:
        return JsonResponse({'error': 'Work not found'}, status=404)

    # Check if work has any extent information
    has_geometry = work.geometry and not work.geometry.empty
    has_temporal = (
        any(d is not None for d in (work.timeperiod_startdate or [])) or
        any(d is not None for d in (work.timeperiod_enddate or []))
    )

    # Allow publishing of contributed publications or harvested publications with at least one extent
    if work.status == 'c':
        # Contributed - can always publish
        old_status = 'Contributed'
    elif work.status == 'h':
        # Harvested - only if it has at least one extent type
        if not (has_geometry or has_temporal):
            return JsonResponse({
                'error': 'Cannot publish harvested work without spatial or temporal extent'
            }, status=400)
        old_status = 'Harvested'
    else:
        return JsonResponse({
            'error': 'Can only publish contributed or harvested publications'
        }, status=400)

    try:
        # Update work
        work.status = 'p'  # Published
        append_event(
            work,
            "publish",
            user_id=request.user.id,
            user_email=request.user.email,
            status_from=old_status.lower()[0],
            status_to="p",
        )
        work.save()

        logger.info(
            "Admin %s published %s work %s (ID: %s)",
            request.user.username, old_status.lower(), work.title[:50], work.id
        )

        # Server-side flash so the post-reload page surfaces a self-closing
        # alert at the top, matching the rest of the app's communication flow.
        messages.success(request, "Work is now public.")

        # Notify the original contributors (if any) that their work is live.
        # Suppressed on republish cycles via provenance.publication_notified_at.
        from works.notifications import notify_work_event
        notify_work_event(work, "publish", actor=request.user)

        return JsonResponse({
            'success': True,
            'message': 'Work is now public!'
        })

    except Exception as e:
        logger.error("Error publishing work: %s", str(e))
        return JsonResponse({'error': str(e)}, status=500)


@staff_member_required
@require_POST
def unpublish_work_by_id(request, work_id):
    """
    API endpoint for admins to unpublish a work by ID.
    Changes status from 'Published' to 'Draft'.
    """
    try:
        work = Work.objects.get(id=work_id)
    except Work.DoesNotExist:
        return JsonResponse({'error': 'Work not found'}, status=404)

    # Only allow unpublishing of published works
    if work.status != 'p':
        return JsonResponse({
            'error': 'Can only unpublish published works'
        }, status=400)

    try:
        # Update work
        work.status = 'd'  # Draft
        append_event(
            work,
            "unpublish",
            user_id=request.user.id,
            user_email=request.user.email,
            status_from="p",
            status_to="d",
        )
        work.save()

        logger.info(
            "Admin %s unpublished work %s (ID: %s)",
            request.user.username, work.title[:50], work.id
        )

        messages.success(request, "Work has been unpublished and set to draft.")

        return JsonResponse({
            'success': True,
            'message': 'Work has been unpublished and set to draft status.'
        })

    except Exception as e:
        logger.error("Error unpublishing work: %s", str(e))
        return JsonResponse({'error': str(e)}, status=500)


# DOI-based views (wrappers that translate DOI to ID)

@require_POST
def contribute_geometry(request, identifier):
    """
    API endpoint for users to contribute geometry to a work by various identifiers.

    Tries to resolve the identifier in this order:
    1. DOI (if identifier contains '/' or starts with '10.')
    2. Internal database ID (if identifier is numeric)
    3. Handle (placeholder for future implementation)

    Delegates to contribute_geometry_by_id after resolving the identifier.
    """

    try:
        work = get_work_by_identifier(identifier)
    except Http404:
        return JsonResponse({'error': 'Work not found'}, status=404)

    return contribute_geometry_by_id(request, work.id)


@staff_member_required
@require_POST
def publish_work(request, identifier):
    """
    API endpoint for admins to publish a work by various identifiers.

    Tries to resolve the identifier in this order:
    1. DOI (if identifier contains '/' or starts with '10.')
    2. Internal database ID (if identifier is numeric)
    3. Handle (placeholder for future implementation)

    Delegates to publish_work_by_id after resolving the identifier.
    """

    try:
        work = get_work_by_identifier(identifier)
    except Http404:
        return JsonResponse({'error': 'Work not found'}, status=404)

    return publish_work_by_id(request, work.id)


@staff_member_required
@require_POST
def unpublish_work(request, identifier):
    """
    API endpoint for admins to unpublish a work by various identifiers.

    Tries to resolve the identifier in this order:
    1. DOI (if identifier contains '/' or starts with '10.')
    2. Internal database ID (if identifier is numeric)
    3. Handle (placeholder for future implementation)

    Delegates to unpublish_work_by_id after resolving the identifier.
    """

    try:
        work = get_work_by_identifier(identifier)
    except Http404:
        return JsonResponse({'error': 'Work not found'}, status=404)

    return unpublish_work_by_id(request, work.id)


# BoK concept contribution ----------------------------------------------------

@require_POST
def contribute_bok_by_id(request, work_id):
    """Add or remove EO4GEO BoK concept tags on a work.

    Body: ``{"add": ["CV","AM10-3"], "remove": ["GIST"]}`` (both optional).
    Codes are validated against the cached BoK snapshot. The first BoK
    contribution on a harvested work flips the status `h → c`; later
    edits leave the status alone.
    """
    if not request.user.is_authenticated:
        return JsonResponse({'error': 'Authentication required'}, status=401)

    try:
        work = Work.objects.get(id=work_id)
    except Work.DoesNotExist:
        return JsonResponse({'error': 'Work not found'}, status=404)

    # Collection gate (OPTIMAP_BOK_ENABLED_COLLECTIONS). Opt-in allow-list:
    # empty -> editor disabled site-wide; populated -> restricted to those
    # collections.
    from works.bok import eligibility as bok_eligibility
    if not bok_eligibility.is_work_eligible(work):
        allowed = bok_eligibility.enabled_collection_identifiers()
        if not allowed:
            msg = 'BoK tagging is not enabled on this OPTIMAP instance.'
        else:
            msg = (
                'BoK tagging is restricted to works in specific collection(s) '
                f'({", ".join(allowed)}); this work is not in any of them.'
            )
        return JsonResponse({'error': msg}, status=403)

    try:
        data = json.loads(request.body or b"{}")
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)

    add = data.get("add") or []
    remove = data.get("remove") or []
    if not isinstance(add, list) or not isinstance(remove, list):
        return JsonResponse({'error': '`add` and `remove` must be arrays of concept codes'}, status=400)
    add = [str(c).strip() for c in add if str(c).strip()]
    remove = [str(c).strip() for c in remove if str(c).strip()]

    if not add and not remove:
        return JsonResponse({'error': 'No concepts provided in `add` or `remove`'}, status=400)

    # Validate `add` codes against the cached snapshot. We don't validate
    # `remove` codes — the user may legitimately be cleaning up an orphan.
    snapshot = bok_client.get_concepts()
    unknown = [c for c in add if c not in snapshot]
    if unknown:
        return JsonResponse({
            'error': f'Unknown BoK concept code(s): {", ".join(sorted(set(unknown)))}'
        }, status=400)

    current = list(work.bok_concepts or [])
    current_set = set(current)
    add_set = set(add) - current_set
    remove_set = set(remove) & current_set

    if not add_set and not remove_set:
        return JsonResponse({
            'success': True,
            'message': 'No changes — concepts already in the requested state.',
            'bok_concepts': sorted(current),
        })

    new_concepts = sorted((current_set | add_set) - remove_set)

    # Status transition: only flip `h → c` when adding (not pure removal).
    status_from = work.status
    status_to = work.status
    if work.status == 'h' and add_set:
        status_to = 'c'

    # Recognition Board dedup decided BEFORE appending the event. The
    # ontology bucket is per-user-per-work (not per-concept) — adding 5
    # concepts in one POST = 1 row, adding 1 more later by the same user
    # = 0 new rows. Removals never count.
    record_ontology_row = (
        bool(add_set)
        and not user_has_contributed_kind(work, request.user.id, "bok")
    )

    work.bok_concepts = new_concepts
    append_event(
        work,
        "contribution",
        user_id=request.user.id,
        user_email=request.user.email,
        kinds=["bok"],
        vocabulary="eo4geo_bok",
        version=getattr(settings, 'BOK_VERSION', 'current'),
        added=sorted(add_set),
        removed=sorted(remove_set),
        status_from=status_from,
        status_to=status_to,
    )
    work.status = status_to
    work.save()

    if record_ontology_row:
        Contribution.objects.create(
            user=request.user, work=work, kind=Contribution.ONTOLOGY,
        )

    logger.info(
        "User %s tagged work %s (ID: %s) BoK +%s -%s",
        request.user.username, work.title[:50], work.id,
        sorted(add_set), sorted(remove_set),
    )

    if add_set:
        from works.notifications import notify_work_event
        notify_work_event(work, "contribution", actor=request.user)

    messages.success(
        request,
        "Thank you for your topic contribution! It is now visible to curators and admins for review.",
    )

    return JsonResponse({
        'success': True,
        'message': 'BoK concepts updated.',
        'added': sorted(add_set),
        'removed': sorted(remove_set),
        'bok_concepts': new_concepts,
        'status': work.status,
    })


@require_POST
def contribute_bok(request, identifier):
    """DOI-/ID-resolving wrapper for `contribute_bok_by_id`."""
    try:
        work = get_work_by_identifier(identifier)
    except Http404:
        return JsonResponse({'error': 'Work not found'}, status=404)
    return contribute_bok_by_id(request, work.id)
