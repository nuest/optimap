# SPDX-FileCopyrightText: 2026 OPTIMETA and KOMET projects <https://projects.tib.eu/komet>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Shared helper for rendering plain-text email templates."""

from django.template import Context
from django.template.loader import get_template


def render_email(template_name: str, context: dict) -> tuple[str, str]:
    """Render a plain-text email template and return ``(subject, body)``.

    The first line of the template is the subject; the remainder (after the
    first blank line) is the body. Autoescape is disabled so URLs and
    special characters are not HTML-encoded in plain-text output.
    """
    backend_template = get_template(template_name)
    # .template is the raw django.template.base.Template — accepts Context directly.
    content = backend_template.template.render(Context(context, autoescape=False))
    subject, _, body = content.partition('\n\n')
    return subject.strip(), body
