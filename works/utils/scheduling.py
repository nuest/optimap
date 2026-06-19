# SPDX-FileCopyrightText: 2022 OPTIMETA and KOMET projects <https://projects.tib.eu/komet>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Helpers for Django-Q scheduled tasks.

The cluster runs with ``Q_CLUSTER["catch_up"] = False`` (see
``optimap/settings.py``), so after the cluster has been down/blocked each
recurring schedule advances to its next future run and fires **once** instead
of replaying every missed slot. Django-Q does not, however, log *that* missed
runs were dropped.

``log_scheduled_catchup`` closes that gap: recurring schedules set
``intended_date_kwarg="scheduled_for"``, so the scheduler injects the intended
fire time (the missed slot) as a ``scheduled_for`` kwarg
(``django_q/scheduler.py``). The decorator compares it to the actual start
time and emits a WARNING when the run is late by more than
``settings.SCHEDULED_TASK_CATCHUP_THRESHOLD_MINUTES``. It never skips the task
and never alters its return value; manual/ad-hoc invocations (no
``scheduled_for``) pass straight through.
"""

import functools
import logging
from datetime import datetime, timedelta

from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)


def log_scheduled_catchup(func):
    """Log a catch-up WARNING when a recurring scheduled run starts late.

    Wrapped functions need not accept ``scheduled_for`` — it is popped before
    the call, so functions with a strict signature (and ones taking no
    arguments) are safe to decorate.
    """

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        scheduled_for = kwargs.pop("scheduled_for", None)
        if scheduled_for:
            try:
                intended = datetime.fromisoformat(scheduled_for)
                delay = timezone.now() - intended
                threshold = timedelta(minutes=settings.SCHEDULED_TASK_CATCHUP_THRESHOLD_MINUTES)
                if delay > threshold:
                    logger.warning(
                        "Scheduled task %s ran %.0f min after its intended time %s; "
                        "intervening missed runs were skipped (catch_up disabled).",
                        func.__name__,
                        delay.total_seconds() / 60,
                        scheduled_for,
                    )
            except (ValueError, TypeError):
                logger.debug("Could not parse scheduled_for=%r for task %s", scheduled_for, func.__name__)
        return func(*args, **kwargs)

    return wrapper
