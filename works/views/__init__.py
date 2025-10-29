"""
Works app views package.

This package organizes views into logical modules:
- auth: Authentication and user account management
- work_views: Work-specific views (landing pages, lists)
- data: Data export endpoints

For backward compatibility, all views are re-exported from this __init__.py
"""

# Import from submodules
from .auth import (
    loginres,
    confirmation_login,
    authenticate_via_magic_link,
    customlogout,
    user_settings,
    user_subscriptions,
    add_subscriptions,
    unsubscribe,
    delete_account,
    change_useremail,
    confirm_email_change,
    request_delete,
    confirm_account_deletion,
    finalize_account_deletion,
)

from .work_views import (
    contribute,
    works_list,
    work_landing,
)

from .data import (
    download_geojson,
    download_geopackage,
    generate_geopackage,
)

# Re-export all for backward compatibility
__all__ = [
    # Auth views
    'loginres',
    'confirmation_login',
    'authenticate_via_magic_link',
    'customlogout',
    'user_settings',
    'user_subscriptions',
    'add_subscriptions',
    'unsubscribe',
    'delete_account',
    'change_useremail',
    'confirm_email_change',
    'request_delete',
    'confirm_account_deletion',
    'finalize_account_deletion',
    # Work views
    'contribute',
    'works_list',
    'work_landing',
    # Data exports
    'download_geojson',
    'download_geopackage',
    'generate_geopackage',
]
