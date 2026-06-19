# SPDX-FileCopyrightText: 2026 OPTIMETA and KOMET projects <https://projects.tib.eu/komet>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Registry of external-service token connectors.

Each entry describes a service whose API credential is stored in the
``works.models.ServiceToken`` table and rotated by staff through the Django
admin. The registry keeps the renewal-reminder machinery (task + email
template) generic: it iterates whatever services are registered here.
OpenAIRE is currently the only entry; adding another connector means adding a
``ServiceTokenSpec`` here (and, for access-token services, an exchange function
like ``works.harvesting.openaire.get_openaire_access_token``).
"""

from dataclasses import dataclass

from django.conf import settings


@dataclass(frozen=True)
class ServiceTokenSpec:
    """Per-service constants used by the admin and the renewal reminder."""

    label: str
    # Lifetime of the stored refresh token, in days (drives expiry/reminder math).
    lifetime_days: int
    # How many days before expiry staff are reminded to renew.
    reminder_days: int
    # Where the provider lets you generate/copy a new refresh token.
    token_page_url: str
    # Provider documentation for the authentication flow.
    docs_url: str
    # Django admin change-view name for the ServiceToken row (deep-link in emails).
    admin_change_viewname: str = "admin:works_servicetoken_change"


def get_service_token_specs() -> dict[str, ServiceTokenSpec]:
    """Return the service registry.

    Built lazily so ``@override_settings`` in tests takes effect.
    """
    return {
        "openaire": ServiceTokenSpec(
            label="OpenAIRE Graph API",
            lifetime_days=settings.OPTIMAP_OPENAIRE_REFRESH_TOKEN_DAYS,
            reminder_days=settings.OPTIMAP_OPENAIRE_RENEWAL_REMINDER_DAYS,
            token_page_url="https://develop.openaire.eu/personal-token",
            docs_url="https://graph.openaire.eu/docs/apis/authentication/",
        ),
    }


def get_spec(service: str) -> ServiceTokenSpec | None:
    """Return the spec for ``service`` or ``None`` if it is not registered."""
    return get_service_token_specs().get(service)
