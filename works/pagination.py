# SPDX-FileCopyrightText: 2026 OPTIMETA and KOMET projects <https://projects.tib.eu/komet>
# SPDX-License-Identifier: GPL-3.0-or-later

from rest_framework.pagination import LimitOffsetPagination
from rest_framework.utils.urls import replace_query_param


class LinkHeaderPagination(LimitOffsetPagination):
    """LimitOffsetPagination that also emits RFC 5988 Link headers."""

    def get_paginated_response(self, data):
        response = super().get_paginated_response(data)
        links = []

        next_url = self.get_next_link()
        prev_url = self.get_previous_link()
        if next_url:
            links.append(f'<{next_url}>; rel="next"')
        if prev_url:
            links.append(f'<{prev_url}>; rel="prev"')

        # Use the full current URL (including any filter/format query params) as
        # the base — same approach as get_next_link() / get_previous_link() in DRF.
        current_url = self.request.build_absolute_uri()
        first_url = replace_query_param(
            replace_query_param(current_url, self.limit_query_param, self.limit),
            self.offset_query_param, 0,
        )
        # True last-page offset: the start of the page that contains the final item.
        # e.g. count=10, limit=3 → last page at offset 9 (not 7).
        last_offset = (max(0, self.count - 1) // self.limit) * self.limit
        last_url = replace_query_param(
            replace_query_param(current_url, self.limit_query_param, self.limit),
            self.offset_query_param, last_offset,
        )
        links.append(f'<{first_url}>; rel="first"')
        links.append(f'<{last_url}>; rel="last"')

        if links:
            response['Link'] = ', '.join(links)
        return response
