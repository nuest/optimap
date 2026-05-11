# SPDX-FileCopyrightText: 2026 OPTIMETA and KOMET projects <https://projects.tib.eu/komet>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Per-work eligibility for the BoK editor.

The `OPTIMAP_BOK_ENABLED_COLLECTIONS` setting (parsed into
`settings.BOK_ENABLED_COLLECTIONS`) is an **opt-in allow-list**: when
empty (default), the BoK editor is disabled site-wide. When populated,
the editor is only available on works that belong to at least one of
the listed collections (matched by `Collection.identifier`). Read-only
chips on existing tags remain visible regardless of the gate — this
setting only controls *who can edit*.

Both the work landing page (UI gate) and the `/contribute-bok/`
endpoint (API gate) call into here so the rule lives in one place.
"""

from __future__ import annotations

from django.conf import settings


def enabled_collection_identifiers() -> list[str]:
    return list(getattr(settings, "BOK_ENABLED_COLLECTIONS", []) or [])


def is_collection_filter_active() -> bool:
    """True when at least one collection is opted in.

    When False, the BoK editor is disabled site-wide.
    """
    return bool(enabled_collection_identifiers())


def is_work_eligible(work) -> bool:
    """Whether the BoK editor may be shown / accepted for this work.

    Returns True only when both:
    - at least one collection is opted in via the setting, AND
    - the work belongs to at least one of those collections
      (matched by `Collection.identifier`).

    Empty allow-list => no work is eligible.
    """
    allowed = enabled_collection_identifiers()
    if not allowed:
        return False
    # `work.collections` is a M2M to Collection. Use a single
    # `.filter(...).exists()` to keep the query cheap.
    try:
        return work.collections.filter(identifier__in=allowed).exists()
    except AttributeError:
        return False
