# SPDX-FileCopyrightText: 2026 OPTIMETA and KOMET projects <https://projects.tib.eu/komet>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Helpers for the contributor recognition board (#240).

Contains the tier definitions, the bucketing function, and the random-username
generator used when a user opts into the recognition board for the first time.
"""

from __future__ import annotations

import re
import secrets
from dataclasses import dataclass
from typing import Iterable, List

from better_profanity import profanity as _profanity
from coolname import generate_slug

from works.models import UserProfile

# Load the default English profanity word list once at import time.
_profanity.load_censor_words()


@dataclass(frozen=True)
class Tier:
    level: int                # 1 (lowest) to 5 (highest)
    min_total: int            # inclusive lower bound on total contributions
    name: str                 # explorer name shown as tier title
    description: str          # short tagline for the recognition board page
    wikipedia_url: str        # link to the explorer's Wikipedia article


# Tiers ordered from highest threshold to lowest. Names taken from
# https://www.historyhit.com/most-important-explorers-of-the-world/ .
RECOGNITION_TIERS: List[Tier] = [
    Tier(level=5, min_total=10000, name="Roald Amundsen",
         description="Reached the South Pole — 10000+ contributions.",
         wikipedia_url="https://en.wikipedia.org/wiki/Roald_Amundsen"),
    Tier(level=4, min_total=1000, name="James Cook",
         description="Charted the Pacific — 1000+ contributions.",
         wikipedia_url="https://en.wikipedia.org/wiki/James_Cook"),
    Tier(level=3, min_total=100, name="Ferdinand Magellan",
         description="First circumnavigation — 100+ contributions.",
         wikipedia_url="https://en.wikipedia.org/wiki/Ferdinand_Magellan"),
    Tier(level=2, min_total=10, name="Vasco da Gama",
         description="Sea route to India — 10+ contributions.",
         wikipedia_url="https://en.wikipedia.org/wiki/Vasco_da_Gama"),
    Tier(level=1, min_total=1, name="Marco Polo",
         description="First steps along the Silk Road — your first contribution.",
         wikipedia_url="https://en.wikipedia.org/wiki/Marco_Polo"),
]


def tier_for(total: int) -> Tier | None:
    """Return the highest tier whose threshold is met, or None for total <= 0."""
    if total <= 0:
        return None
    for tier in RECOGNITION_TIERS:  # ordered from highest to lowest
        if total >= tier.min_total:
            return tier
    return None


def group_by_tier(entries: Iterable) -> List[tuple]:
    """Group an iterable of entries (each with `.total` attribute) into tiers.

    Returns a list of `(tier, [entries])` pairs in descending tier order.
    All five tiers are always present, even when empty, so the page renders
    a stable structure.
    """
    buckets: dict[int, list] = {t.level: [] for t in RECOGNITION_TIERS}
    for entry in entries:
        tier = tier_for(getattr(entry, "total", 0))
        if tier is not None:
            buckets[tier.level].append(entry)
    return [(t, buckets[t.level]) for t in RECOGNITION_TIERS]


# --- Random username generation ---------------------------------------------

USERNAME_REGEX = re.compile(r"^[\-A-Za-z0-9_]{3,64}$")


def is_offensive(username: str) -> bool:
    """Return True if `username` contains a profane word.

    Splits on `-` and `_` so slug-style names ("clever-puffin") are checked
    word-by-word — the default list matches whole words, and joining with
    spaces is what `better-profanity` expects. Best-effort only; profanity
    filters always have false positives and false negatives.
    """
    if not username:
        return False
    parts = re.split(r"[-_]", username)
    return _profanity.contains_profanity(" ".join(parts))


def generate_random_username(max_attempts: int = 5) -> str:
    """Generate a unique slug-style username for the recognition board.

    Uses `coolname` to produce two-word slugs like ``clever-puffin``. Falls back
    to appending a numeric suffix if all attempts collide with existing values
    in `UserProfile.recognition_username`.
    """
    taken = set(
        UserProfile.objects.exclude(recognition_username__isnull=True)
        .values_list("recognition_username", flat=True)
    )
    for _ in range(max_attempts):
        candidate = generate_slug(2)
        if (candidate not in taken
                and len(candidate) <= 64
                and not is_offensive(candidate)):
            return candidate
    # Last-resort fallback: tack on a 4-digit suffix.
    base = generate_slug(2)[:59]
    return f"{base}-{secrets.randbelow(10000):04d}"
