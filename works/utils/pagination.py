# SPDX-FileCopyrightText: 2026 OPTIMETA and KOMET projects <https://projects.tib.eu/komet>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Shared work-list pagination for the HTML landing/list views.

Centralizes the ``?size`` clamp + ``Paginator`` + ``EmptyPage``/
``PageNotAnInteger`` handling that the source, facet, region, and collection
list views would otherwise each copy (so the clamping rules and last-page
behaviour can't drift between them).
"""

from django.conf import settings
from django.core.paginator import EmptyPage, PageNotAnInteger, Paginator


def paginate_works(request, works, *, decorate=None):
    """Return ``(page_obj, page_size)`` for ``works`` using the request's
    ``?size`` / ``?page`` params, with ``page_size`` clamped to the configured
    bounds. ``decorate`` (optional) is called once per work on the chosen page —
    use it to attach view-specific render helpers (e.g. COinS context).
    """
    try:
        page_size = int(request.GET.get("size", settings.WORKS_PAGE_SIZE_DEFAULT))
        page_size = max(settings.WORKS_PAGE_SIZE_MIN, min(page_size, settings.WORKS_PAGE_SIZE_MAX))
    except (ValueError, TypeError):
        page_size = settings.WORKS_PAGE_SIZE_DEFAULT

    paginator = Paginator(works, page_size)
    try:
        page_obj = paginator.page(request.GET.get("page", 1))
    except PageNotAnInteger:
        page_obj = paginator.page(1)
    except EmptyPage:
        page_obj = paginator.page(paginator.num_pages)

    if decorate is not None:
        for work in page_obj.object_list:
            decorate(work)

    return page_obj, page_size
