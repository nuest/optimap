# SPDX-FileCopyrightText: 2022 OPTIMETA and KOMET projects <https://projects.tib.eu/komet>
# SPDX-License-Identifier: GPL-3.0-or-later

import logging
logger = logging.getLogger(__name__)

from django.db.models.signals import pre_save
from django.dispatch import receiver
from django.contrib.auth import get_user_model
User = get_user_model()
from django.conf import settings
from django.db.models.signals import post_save
User = get_user_model() 
from works.models import UserProfile

@receiver(pre_save, sender=User)
def update_user_callback(sender, instance, **kwargs):
    logging.info('New user added: ', instance.email)

    if instance.email in settings.OPTIMAP_SUPERUSER_EMAILS and not instance.is_superuser:
        logging.warning('Registering user %s as admin', instance.email)
        instance.is_staff = True
        instance.is_superuser = True

@receiver(post_save, sender=User)
def create_or_update_user_profile(sender, instance, created, **kwargs):
    if created:
        UserProfile.objects.create(user=instance)
    else:
        instance.userprofile.save()


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
        logger.debug("preview cache invalidation failed for work %s: %s",
                     instance.pk, err)
