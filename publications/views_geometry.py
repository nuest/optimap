"""
Views for geometry contribution and publication management.
"""
import logging
import json
from django.contrib.auth.decorators import login_required
from django.contrib.admin.views.decorators import staff_member_required
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.views.decorators.csrf import csrf_exempt
from django.contrib.gis.geos import GEOSGeometry
from django.utils import timezone
from publications.models import Publication

logger = logging.getLogger(__name__)


# Core ID-based views (internal implementation)

@require_POST
def contribute_geometry_by_id(request, pub_id):
    """
    API endpoint for users to contribute geometry and/or temporal extent to a publication by ID.
    Used for publications without a DOI.
    Changes status from 'Harvested' to 'Contributed'.
    """
    # Check authentication for AJAX requests
    if not request.user.is_authenticated:
        return JsonResponse({'error': 'Authentication required'}, status=401)

    try:
        pub = Publication.objects.get(id=pub_id)
    except Publication.DoesNotExist:
        return JsonResponse({'error': 'Publication not found'}, status=404)

    # Only allow contributions to harvested publications
    if pub.status != 'h':
        return JsonResponse({
            'error': 'Can only contribute to harvested publications'
        }, status=400)

    try:
        # Parse request data
        data = json.loads(request.body)
        geojson = data.get('geometry')
        temporal_extent = data.get('temporal_extent')

        logger.info("Received contribution request for publication ID: %s, data: %s", pub_id, data)

        if not geojson and not temporal_extent:
            logger.warning("No geometry or temporal extent provided in request")
            return JsonResponse({'error': 'No geometry or temporal extent provided'}, status=400)

        # Build contribution note
        old_provenance = pub.provenance or ''
        contribution_parts = []
        changes_made = []

        # Handle geometry contribution
        if geojson:
            # Check if geometry already exists
            if pub.geometry and not pub.geometry.empty:
                return JsonResponse({
                    'error': 'Publication already has geometry'
                }, status=400)

            # Convert GeoJSON to GeometryCollection
            logger.info("Converting geometry: %s", geojson)
            geometry = GEOSGeometry(json.dumps(geojson))
            pub.geometry = geometry
            changes_made.append(f"Changed geometry from empty to {geometry.geom_type}")

        # Handle temporal extent contribution
        if temporal_extent:
            start_date = temporal_extent.get('start_date')
            end_date = temporal_extent.get('end_date')

            if start_date:
                pub.timeperiod_startdate = [start_date]
                changes_made.append(f"Set start date to {start_date}")
            if end_date:
                pub.timeperiod_enddate = [end_date]
                changes_made.append(f"Set end date to {end_date}")

        # Create provenance note
        contribution_note = (
            f"\n\nContribution by user {request.user.username} "
            f"({request.user.email}) on {timezone.now().isoformat()}. "
            + ". ".join(changes_made) + ". "
            f"Status changed from Harvested to Contributed."
        )

        pub.status = 'c'  # Contributed
        pub.provenance = old_provenance + contribution_note
        pub.save()

        logger.info(
            "User %s contributed to publication %s (ID: %s): %s",
            request.user.username, pub.title[:50], pub.id, ", ".join(changes_made)
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
def publish_work_by_id(request, pub_id):
    """
    API endpoint for admins to publish a work by ID.
    Used for publications without a DOI.
    Changes status from 'Contributed' or 'Harvested' to 'Published'.
    For harvested publications, requires that at least one extent (spatial or temporal) exists.
    """
    try:
        pub = Publication.objects.get(id=pub_id)
    except Publication.DoesNotExist:
        return JsonResponse({'error': 'Publication not found'}, status=404)

    # Check if publication has any extent information
    has_geometry = pub.geometry and not pub.geometry.empty
    has_temporal = bool(pub.timeperiod_startdate or pub.timeperiod_enddate)

    # Allow publishing of contributed publications or harvested publications with at least one extent
    if pub.status == 'c':
        # Contributed - can always publish
        old_status = 'Contributed'
    elif pub.status == 'h':
        # Harvested - only if it has at least one extent type
        if not (has_geometry or has_temporal):
            return JsonResponse({
                'error': 'Cannot publish harvested publication without spatial or temporal extent'
            }, status=400)
        old_status = 'Harvested'
    else:
        return JsonResponse({
            'error': 'Can only publish contributed or harvested publications'
        }, status=400)

    try:
        # Update publication
        old_provenance = pub.provenance or ''
        publish_note = (
            f"\n\nPublished by admin {request.user.username} "
            f"({request.user.email}) on {timezone.now().isoformat()}. "
            f"Status changed from {old_status} to Published."
        )

        pub.status = 'p'  # Published
        pub.provenance = old_provenance + publish_note
        pub.save()

        logger.info(
            "Admin %s published %s publication %s (ID: %s)",
            request.user.username, old_status.lower(), pub.title[:50], pub.id
        )

        return JsonResponse({
            'success': True,
            'message': 'Publication is now public!'
        })

    except Exception as e:
        logger.error("Error publishing work: %s", str(e))
        return JsonResponse({'error': str(e)}, status=500)


@staff_member_required
@require_POST
def unpublish_work_by_id(request, pub_id):
    """
    API endpoint for admins to unpublish a work by ID.
    Changes status from 'Published' to 'Draft'.
    """
    try:
        pub = Publication.objects.get(id=pub_id)
    except Publication.DoesNotExist:
        return JsonResponse({'error': 'Publication not found'}, status=404)

    # Only allow unpublishing of published works
    if pub.status != 'p':
        return JsonResponse({
            'error': 'Can only unpublish published works'
        }, status=400)

    try:
        # Update publication
        old_provenance = pub.provenance or ''
        unpublish_note = (
            f"\n\nUnpublished by admin {request.user.username} "
            f"({request.user.email}) on {timezone.now().isoformat()}. "
            f"Status changed from Published to Draft."
        )

        pub.status = 'd'  # Draft
        pub.provenance = old_provenance + unpublish_note
        pub.save()

        logger.info(
            "Admin %s unpublished publication %s (ID: %s)",
            request.user.username, pub.title[:50], pub.id
        )

        return JsonResponse({
            'success': True,
            'message': 'Publication has been unpublished and set to draft status.'
        })

    except Exception as e:
        logger.error("Error unpublishing work: %s", str(e))
        return JsonResponse({'error': str(e)}, status=500)


# DOI-based views (wrappers that translate DOI to ID)

@require_POST
def contribute_geometry(request, doi):
    """
    API endpoint for users to contribute geometry to a publication by DOI.
    Wrapper that translates DOI to ID and delegates to contribute_geometry_by_id.
    """
    try:
        pub = Publication.objects.get(doi=doi)
        return contribute_geometry_by_id(request, pub.id)
    except Publication.DoesNotExist:
        return JsonResponse({'error': 'Publication not found'}, status=404)


@staff_member_required
@require_POST
def publish_work(request, doi):
    """
    API endpoint for admins to publish a work by DOI.
    Wrapper that translates DOI to ID and delegates to publish_work_by_id.
    """
    try:
        pub = Publication.objects.get(doi=doi)
        return publish_work_by_id(request, pub.id)
    except Publication.DoesNotExist:
        return JsonResponse({'error': 'Publication not found'}, status=404)


@staff_member_required
@require_POST
def unpublish_work(request, doi):
    """
    API endpoint for admins to unpublish a work by DOI.
    Wrapper that translates DOI to ID and delegates to unpublish_work_by_id.
    """
    try:
        pub = Publication.objects.get(doi=doi)
        return unpublish_work_by_id(request, pub.id)
    except Publication.DoesNotExist:
        return JsonResponse({'error': 'Publication not found'}, status=404)
