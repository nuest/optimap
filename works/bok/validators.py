# SPDX-FileCopyrightText: 2026 OPTIMETA and KOMET projects <https://projects.tib.eu/komet>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Validators for BoK concept codes.

Used both by the contribution endpoint (rejects unknown codes at submit
time) and by tests. We do *not* run this on `Work.clean()` because
existing code values may legitimately become orphans when upstream
removes them — see the orphan-rendering rule on the landing page.
"""

import re

from django.core.exceptions import ValidationError

from works.bok.client import is_known

# Concept codes are short, alphanumeric, may include dashes
# (e.g. "AM10-3"). Hard-cap length at 32 chars to match the model field.
_CODE_RE = re.compile(r"^[A-Za-z0-9_-]{1,32}$")


def is_valid_code_format(code: str) -> bool:
    return bool(code) and bool(_CODE_RE.match(code))


def validate_known_code(code: str) -> None:
    if not is_valid_code_format(code):
        raise ValidationError(f"Invalid BoK concept code format: {code!r}")
    if not is_known(code):
        raise ValidationError(f"Unknown BoK concept code: {code!r}")
