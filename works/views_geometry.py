# SPDX-FileCopyrightText: 2025 OPTIMETA and KOMET projects <https://projects.tib.eu/komet>
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Views for geometry contribution and work management.
"""

import json
import logging

from django.conf import settings
from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.gis.geos import GEOSGeometry
from django.http import Http404, JsonResponse
from django.views.decorators.http import require_POST

from works.bok import client as bok_client
from works.models import Contribution, Work
from works.utils.geometry import sanitize_geojson_geometry
from works.utils.identifiers import get_work_by_identifier
from works.utils.provenance import append_event, user_has_contributed_kind

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
        return JsonResponse({"error": "Authentication required"}, status=401)

    try:
        work = Work.objects.get(id=work_id)
    except Work.DoesNotExist:
        return JsonResponse({"error": "Work not found"}, status=404)

    is_admin = request.user.is_staff
    if work.status not in ("h", "c") and not (is_admin and work.status == "d"):
        return JsonResponse({"error": "Can only contribute to harvested or contributed publications"}, status=400)

    try:
        data = json.loads(request.body)
        geojson = data.get("geometry")
        temporal_extent = data.get("temporal_extent")
        provenance_hint = data.get("provenance_hint")
        game = True if data.get("game") else None

        logger.info("Received contribution request for work ID: %s, data: %s", work_id, data)

        # Normalise temporal input: accept either a single-period object
        # (legacy ``temporal_extent``) or a list of periods
        # (``temporal_extents``).  The list form takes precedence when both
        # are present.
        temporal_extents = data.get("temporal_extents")
        if temporal_extents is not None:
            periods = temporal_extents if isinstance(temporal_extents, list) else [temporal_extents]
        elif temporal_extent:
            periods = [temporal_extent]
        else:
            periods = []

        if not geojson and not periods:
            logger.warning("No geometry or temporal extent provided in request")
            return JsonResponse({"error": "No geometry or temporal extent provided"}, status=400)

        changes_made = []
        spatial_contributed = False
        temporal_contributed = False
        geometry_warning = None

        if geojson:
            had_geometry = bool(work.geometry and not work.geometry.empty)
            logger.info("Converting geometry: %s", geojson)
            # Drop degenerate rings (e.g. tiny interior holes collapsed to a
            # repeated point by client-side simplification) before handing the
            # GeoJSON to GEOS, which rejects LinearRings with < 4 points.
            geojson, dropped_rings = sanitize_geojson_geometry(geojson)
            try:
                geometry = GEOSGeometry(json.dumps(geojson))
            except Exception as e:
                logger.warning("Rejected invalid contributed geometry for work %s: %s", work_id, e)
                return JsonResponse({"error": f"Invalid geometry: {e}"}, status=400)
            if geometry.empty:
                # Everything was degenerate and got dropped — nothing to save.
                logger.warning("Contributed geometry for work %s was empty after sanitization", work_id)
                return JsonResponse(
                    {"error": "Invalid geometry: no valid geometry remained after removing degenerate parts."},
                    status=400,
                )
            work.geometry = geometry
            changes_made.append(
                f"{'Replaced geometry with' if had_geometry else 'Changed geometry from empty to'} "
                f"{geometry.geom_type}"
            )
            if dropped_rings:
                changes_made.append(f"Removed {dropped_rings} invalid geometry ring(s)")
                geometry_warning = (
                    f"{dropped_rings} invalid part(s) of your geometry "
                    "(e.g. tiny holes that collapsed during simplification) "
                    "were removed before saving."
                )
            spatial_contributed = True

        if periods:
            starts = [p.get("start_date") or None for p in periods]
            ends = [p.get("end_date") or None for p in periods]

            any_start = any(s for s in starts)
            any_end = any(e for e in ends)

            if any_start:
                work.timeperiod_startdate = starts if any_start else None
                changes_made.append(f"Set start date(s) to {', '.join(s for s in starts if s)}")
                temporal_contributed = True
            else:
                work.timeperiod_startdate = None

            if any_end:
                work.timeperiod_enddate = ends if any_end else None
                changes_made.append(f"Set end date(s) to {', '.join(e for e in ends if e)}")
                temporal_contributed = True
            else:
                work.timeperiod_enddate = None

            if not temporal_contributed:
                # All fields blank — treat as no temporal input
                periods = []

        # Recognition Board dedup decisions taken BEFORE we record this
        # event, so the new event doesn't count against itself.
        record_spatial_row = spatial_contributed and not user_has_contributed_kind(work, request.user.id, "spatial")
        record_temporal_row = temporal_contributed and not user_has_contributed_kind(work, request.user.id, "temporal")

        status_from = work.status
        # Harvested works flip to Contributed on the first contribution;
        # already-Contributed and Draft works stay where they are.
        status_to = work.status if work.status in ("c", "d") else "c"

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
            game=game,
        )
        work.status = status_to
        work.save()

        if record_spatial_row:
            Contribution.objects.create(user=request.user, work=work, kind=Contribution.SPATIAL)
        if record_temporal_row:
            Contribution.objects.create(user=request.user, work=work, kind=Contribution.TEMPORAL)

        logger.info(
            "User %s contributed to work %s (ID: %s): %s",
            request.user.username,
            work.title[:50],
            work.id,
            ", ".join(changes_made),
        )

        from works.notifications import notify_work_event

        notify_work_event(work, "contribution", actor=request.user)

        messages.success(
            request,
            "Thank you for your contribution! It is now visible to curators and admins for review.",
        )
        if geometry_warning:
            # Surfaced as a self-closing flash on the reloaded page, matching
            # the rest of the app's communication flow.
            messages.warning(request, geometry_warning)

        response_data = {
            "success": True,
            "message": "Thank you for your contribution! An administrator will review your changes.",
        }
        if geometry_warning:
            response_data["warning"] = geometry_warning
        return JsonResponse(response_data)

    except json.JSONDecodeError as e:
        logger.error("JSON decode error: %s", str(e))
        return JsonResponse({"error": "Invalid JSON"}, status=400)
    except Exception as e:
        logger.error("Error saving contribution: %s", str(e), exc_info=True)
        return JsonResponse({"error": str(e)}, status=500)


@require_POST
def publish_work_by_id(request, work_id):
    """
    API endpoint for admins and collection curators to publish a work by ID.
    Changes status from Contributed, Harvested, or Draft to Published.
    Harvested works require at least one spatial or temporal extent.
    """
    if not request.user.is_authenticated:
        return JsonResponse({"error": "Authentication required"}, status=401)

    try:
        work = Work.objects.get(id=work_id)
    except Work.DoesNotExist:
        return JsonResponse({"error": "Work not found"}, status=404)

    is_staff = request.user.is_staff
    is_curator = not is_staff and work.collections.filter(curators=request.user).exists()
    if not (is_staff or is_curator):
        return JsonResponse({"error": "Permission denied"}, status=403)

    # Check if work has any extent information
    has_geometry = work.geometry and not work.geometry.empty
    has_temporal = any(d is not None for d in (work.timeperiod_startdate or [])) or any(
        d is not None for d in (work.timeperiod_enddate or [])
    )

    if work.status == "c":
        old_status = "Contributed"
    elif work.status == "d":
        old_status = "Draft"
    elif work.status == "h":
        if not (has_geometry or has_temporal):
            return JsonResponse(
                {"error": "Cannot publish harvested work without spatial or temporal extent"}, status=400
            )
        old_status = "Harvested"
    else:
        return JsonResponse({"error": "Can only publish contributed, draft, or harvested publications"}, status=400)

    try:
        # Update work
        work.status = "p"  # Published
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
            request.user.username,
            old_status.lower(),
            work.title[:50],
            work.id,
        )

        # Server-side flash so the post-reload page surfaces a self-closing
        # alert at the top, matching the rest of the app's communication flow.
        messages.success(request, "Work is now public.")

        # Notify the original contributors (if any) that their work is live.
        # Suppressed on republish cycles via provenance.publication_notified_at.
        from works.notifications import notify_work_event

        notify_work_event(work, "publish", actor=request.user)

        return JsonResponse({"success": True, "message": "Work is now public!"})

    except Exception as e:
        logger.error("Error publishing work: %s", str(e))
        return JsonResponse({"error": str(e)}, status=500)


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
        return JsonResponse({"error": "Work not found"}, status=404)

    # Only allow unpublishing of published works
    if work.status != "p":
        return JsonResponse({"error": "Can only unpublish published works"}, status=400)

    try:
        # Update work
        work.status = "d"  # Draft
        append_event(
            work,
            "unpublish",
            user_id=request.user.id,
            user_email=request.user.email,
            status_from="p",
            status_to="d",
        )
        work.save()

        logger.info("Admin %s unpublished work %s (ID: %s)", request.user.username, work.title[:50], work.id)

        messages.success(request, "Work has been unpublished and set to draft.")

        return JsonResponse({"success": True, "message": "Work has been unpublished and set to draft status."})

    except Exception as e:
        logger.error("Error unpublishing work: %s", str(e))
        return JsonResponse({"error": str(e)}, status=500)


def _extents_message(info):
    """Human-readable suffix describing the geometry/temporal re-harvest outcome.

    ``info`` is the dict returned by ``reharvest_work`` (geometry/temporal each
    one of ``updated`` / ``preserved_user_contribution`` / ``no_source_value`` /
    ``skipped``). Communicates clearly when a value was left untouched because a
    user had contributed it.
    """
    labels = {
        "geometry": "Geometry",
        "temporal": "Temporal extent",
    }
    parts = []
    for field, label in labels.items():
        status = (info or {}).get(field)
        if status == "updated":
            parts.append(f"{label} updated from source.")
        elif status == "preserved_user_contribution":
            parts.append(f"{label} preserved (user-contributed, not overridden).")
        elif status == "no_source_value":
            parts.append(f"No {label.lower()} found at source (existing kept).")
    return (" " + " ".join(parts)) if parts else ""


@staff_member_required
@require_POST
def reharvest_work_by_id(request, work_id):
    """API endpoint for admins to re-harvest a single work by ID.

    Re-fetches the work's metadata from Crossref by DOI and re-runs all
    enrichment steps (OpenAlex inline + OpenAIRE) synchronously, updating the
    work in place with the careful-update policy (user/curator contributions
    such as status, geometry, and temporal extent are preserved). Requires the
    work to have a DOI.
    """
    try:
        work = Work.objects.get(id=work_id)
    except Work.DoesNotExist:
        return JsonResponse({"error": "Work not found"}, status=404)

    if not work.doi:
        return JsonResponse({"error": "Cannot re-harvest a work without a DOI"}, status=400)

    try:
        from works.harvesting.crossref import reharvest_work as _reharvest

        _work, action, info = _reharvest(work, user=request.user)

        if action == "updated":
            logger.info("Admin %s re-harvested work %s (ID: %s)", request.user.username, work.title[:50], work.id)
            message = "Work metadata re-harvested from the original source." + _extents_message(info)
            messages.success(request, message)
            return JsonResponse({"success": True, "message": message})
        if action == "no_doi":
            return JsonResponse({"error": "Cannot re-harvest a work without a DOI"}, status=400)
        # action == "not_found"
        return JsonResponse({"error": "No record found for this DOI at the source"}, status=404)

    except Exception as e:
        logger.error("Error re-harvesting work %s: %s", work_id, str(e), exc_info=True)
        return JsonResponse({"error": str(e)}, status=500)


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
        return JsonResponse({"error": "Work not found"}, status=404)

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
        return JsonResponse({"error": "Work not found"}, status=404)

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
        return JsonResponse({"error": "Work not found"}, status=404)

    return unpublish_work_by_id(request, work.id)


@staff_member_required
@require_POST
def reharvest_work(request, identifier):
    """API endpoint for admins to re-harvest a work by various identifiers.

    Resolves the identifier (DOI / internal ID / handle) and delegates to
    reharvest_work_by_id.
    """

    try:
        work = get_work_by_identifier(identifier)
    except Http404:
        return JsonResponse({"error": "Work not found"}, status=404)

    return reharvest_work_by_id(request, work.id)


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
        return JsonResponse({"error": "Authentication required"}, status=401)

    try:
        work = Work.objects.get(id=work_id)
    except Work.DoesNotExist:
        return JsonResponse({"error": "Work not found"}, status=404)

    # Collection gate (OPTIMAP_BOK_ENABLED_COLLECTIONS). Opt-in allow-list:
    # empty -> editor disabled site-wide; populated -> restricted to those
    # collections.
    from works.bok import eligibility as bok_eligibility

    if not bok_eligibility.is_work_eligible(work):
        allowed = bok_eligibility.enabled_collection_identifiers()
        if not allowed:
            msg = "BoK tagging is not enabled on this OPTIMAP instance."
        else:
            msg = (
                "BoK tagging is restricted to works in specific collection(s) "
                f"({', '.join(allowed)}); this work is not in any of them."
            )
        return JsonResponse({"error": msg}, status=403)

    try:
        data = json.loads(request.body or b"{}")
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON"}, status=400)

    add = data.get("add") or []
    remove = data.get("remove") or []
    if not isinstance(add, list) or not isinstance(remove, list):
        return JsonResponse({"error": "`add` and `remove` must be arrays of concept codes"}, status=400)
    add = [str(c).strip() for c in add if str(c).strip()]
    remove = [str(c).strip() for c in remove if str(c).strip()]

    if not add and not remove:
        return JsonResponse({"error": "No concepts provided in `add` or `remove`"}, status=400)

    # Validate `add` codes against the cached snapshot. We don't validate
    # `remove` codes — the user may legitimately be cleaning up an orphan.
    snapshot = bok_client.get_concepts()
    unknown = [c for c in add if c not in snapshot]
    if unknown:
        return JsonResponse({"error": f"Unknown BoK concept code(s): {', '.join(sorted(set(unknown)))}"}, status=400)

    current = list(work.bok_concepts or [])
    current_set = set(current)
    add_set = set(add) - current_set
    remove_set = set(remove) & current_set

    if not add_set and not remove_set:
        return JsonResponse(
            {
                "success": True,
                "message": "No changes — concepts already in the requested state.",
                "bok_concepts": sorted(current),
            }
        )

    new_concepts = sorted((current_set | add_set) - remove_set)

    # Status transition: only flip `h → c` when adding (not pure removal).
    status_from = work.status
    status_to = work.status
    if work.status == "h" and add_set:
        status_to = "c"

    # Recognition Board dedup decided BEFORE appending the event. The
    # ontology bucket is per-user-per-work (not per-concept) — adding 5
    # concepts in one POST = 1 row, adding 1 more later by the same user
    # = 0 new rows. Removals never count.
    record_ontology_row = bool(add_set) and not user_has_contributed_kind(work, request.user.id, "bok")

    work.bok_concepts = new_concepts
    append_event(
        work,
        "contribution",
        user_id=request.user.id,
        user_email=request.user.email,
        kinds=["bok"],
        vocabulary="eo4geo_bok",
        version=getattr(settings, "BOK_VERSION", "current"),
        added=sorted(add_set),
        removed=sorted(remove_set),
        status_from=status_from,
        status_to=status_to,
    )
    work.status = status_to
    work.save()

    if record_ontology_row:
        Contribution.objects.create(
            user=request.user,
            work=work,
            kind=Contribution.ONTOLOGY,
        )

    logger.info(
        "User %s tagged work %s (ID: %s) BoK +%s -%s",
        request.user.username,
        work.title[:50],
        work.id,
        sorted(add_set),
        sorted(remove_set),
    )

    if add_set:
        from works.notifications import notify_work_event

        notify_work_event(work, "contribution", actor=request.user)

    messages.success(
        request,
        "Thank you for your topic contribution! It is now visible to curators and admins for review.",
    )

    return JsonResponse(
        {
            "success": True,
            "message": "BoK concepts updated.",
            "added": sorted(add_set),
            "removed": sorted(remove_set),
            "bok_concepts": new_concepts,
            "status": work.status,
        }
    )


@require_POST
def contribute_bok(request, identifier):
    """DOI-/ID-resolving wrapper for `contribute_bok_by_id`."""
    try:
        work = get_work_by_identifier(identifier)
    except Http404:
        return JsonResponse({"error": "Work not found"}, status=404)
    return contribute_bok_by_id(request, work.id)
