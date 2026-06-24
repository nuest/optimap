# SPDX-FileCopyrightText: 2022 OPTIMETA and KOMET projects <https://projects.tib.eu/komet>
# SPDX-License-Identifier: GPL-3.0-or-later

import logging

logger = logging.getLogger(__name__)

from django.contrib.auth import get_user_model
from django.db.models.signals import pre_delete, pre_save
from django.dispatch import receiver

User = get_user_model()
from django.conf import settings
from django.db.models.signals import post_save
from django.utils import timezone

User = get_user_model()
from works.models import UserProfile


@receiver(pre_save, sender=User)
def update_user_callback(sender, instance, **kwargs):
    logging.info("New user added: %s", instance.email)

    if instance.email and instance.email in settings.OPTIMAP_SUPERUSER_EMAILS and not instance.is_superuser:
        logging.warning("Registering user %s as admin", instance.email)
        instance.is_staff = True
        instance.is_superuser = True


@receiver(post_save, sender=User)
def create_or_update_user_profile(sender, instance, created, **kwargs):
    if created:
        UserProfile.objects.create(user=instance)
    else:
        # get_or_create guards against legacy/admin-created accounts that
        # were never run through the OPTIMAP login flow and have no profile.
        UserProfile.objects.get_or_create(user=instance)


@receiver(pre_delete, sender=User)
def reassign_contributions_before_user_delete(sender, instance, **kwargs):
    """Move contributions to the sentinel before a user is deleted."""
    from works.models import Contribution, CustomUser

    try:
        sentinel = CustomUser.deleted_user()
    except CustomUser.DoesNotExist:
        return
    if instance.pk == sentinel.pk:
        return
    Contribution.objects.filter(user=instance).update(user=sentinel)


# --- SEO preview-image cache invalidation (issue #22) -----------------------
# (The landing-page context cache from issue #180 is keyed on
# ``work.lastUpdate``, which Django auto-bumps to ``now()`` on every save,
# so it self-invalidates without an explicit signal.)
from works.models import Work as _Work


@receiver(post_save, sender=_Work)
def invalidate_work_preview_cache(sender, instance, **kwargs):
    """Drop the cached og:image PNG for the work whenever the work is saved.
    Lazy regeneration on the next request is cheap (a few hundred ms) and
    keeps stale geometry/title from leaking into social previews."""
    try:
        from works.services.preview_image import invalidate_preview

        invalidate_preview(instance)
    except Exception as err:  # pragma: no cover — non-critical path
        logger.debug("preview cache invalidation failed for work %s: %s", instance.pk, err)


# --- Reverse-geocoded placename (#222) + offline country assignment (#261) ---


@receiver(pre_save, sender=_Work)
def update_work_placename(sender, instance, **kwargs):
    """Populate ``placename`` via per-point reverse geocoding.

    Gated by ``OPTIMAP_GEOCODE_WORKS_ON_SAVE`` — defaults to ``True`` in
    production and is forced off under the test runner (see ``settings.py``).
    Skipped when the work has no geometry.

    Multi-point geometries are geocoded per-site and reduced to the lowest
    common ancestor in the address hierarchy — a work covering Berlin and
    Munich becomes ``"Germany"`` rather than the misleading
    centroid-of-Berlin-and-Munich result. See
    ``works.services.geocoding.geocode_geometry``.

    Country association is *not* set here: it lives in the ``Work.countries``
    M2M, populated by the offline point-in-polygon join in
    ``assign_work_countries`` (post-save) — see issue #261.

    On a complete geocoding failure (no point returned an address — typically
    a transient Nominatim outage) we leave the existing fields untouched
    rather than blank a previously-populated placename. A real "geometry
    spans incompatible regions" result (some addresses, no shared LCA)
    *does* clear the fields — that's the honest representation.
    """
    if not getattr(settings, "GEOCODE_WORKS_ON_SAVE", False):
        return
    geom = instance.geometry
    if not geom or geom.empty:
        return
    try:
        from works.services.geocoding import (
            collect_geocoding_matches,
            geocode_geometry,
        )

        placename, _country_code, n_geocoded = geocode_geometry(geom)
    except Exception as err:  # pragma: no cover — geocode_geometry never raises
        logger.warning("reverse-geocode failed for work %s: %s", instance.pk, err)
        return
    if n_geocoded == 0:
        # All Nominatim calls failed — preserve any populated fields, and
        # leave any existing geocoding-provenance block untouched (it still
        # describes the values currently in the DB).
        return
    instance.placename = placename

    # Per-point matches (cache hit since geocode_geometry just populated it).
    # For multi-point geometries the LCA placename is broader than any single
    # match, so the honest representation is the list of underlying matches
    # that produced it — each one with its OSM identifiers.
    try:
        matches = collect_geocoding_matches(geom)
    except Exception as err:  # pragma: no cover — defensive
        logger.warning("collect_geocoding_matches failed for work %s: %s", instance.pk, err)
        matches = []

    # Record reverse-geocoding provenance — single block, overwritten on each
    # successful run, so it always describes the current placename.
    provenance = instance.provenance if isinstance(instance.provenance, dict) else {}
    provenance["geocoding"] = {
        "gazetteer": "Nominatim",
        "gazetteer_url": "https://nominatim.openstreetmap.org/",
        "placename": placename,
        "n_geocoded": n_geocoded,
        "matches": matches,
        "geocoded_at": timezone.now().isoformat(),
    }
    instance.provenance = provenance


@receiver(post_save, sender=_Work)
def assign_work_countries(sender, instance, **kwargs):
    """Populate ``Work.countries`` via an offline point-in-polygon join (#261).

    Runs post-save (M2M needs a PK). Gated by ``OPTIMAP_GEOCODE_WORKS_ON_SAVE``
    for parity with the Nominatim placename signal — the recurring sweep
    (``works.tasks.backfill_work_countries``) is the guaranteed catch-up path
    for works saved with it off, during a load before ``load_countries``, or
    legacy records. Naturally multi-valued: a transboundary geometry links
    every intersecting country. ``set()`` does not re-fire ``Work`` save, so
    there is no recursion.
    """
    if not getattr(settings, "GEOCODE_WORKS_ON_SAVE", False):
        return
    geom = instance.geometry
    if not geom or geom.empty:
        return
    try:
        from works.services.countries import countries_for_geometry

        instance.countries.set(countries_for_geometry(geom))
    except Exception as err:  # pragma: no cover — non-critical path
        logger.warning("country assignment failed for work %s: %s", instance.pk, err)
