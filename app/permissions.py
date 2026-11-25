"""Single source of truth for role-based access (the permission matrix in docs/auth.md).

Usage in a router:
    @router.post('', dependencies=allow('orders:write'))
or, when the handler needs the current member (e.g. changed_by for order history):
    def change_status(..., principal: Annotated[Principal, Depends(require_permission('orders:change-status'))])

Rule from the assignment: ADMIN manages everything; OPERATOR enters/edits data and changes
order status; VIEWER only reads data and metrics.
"""
from fastapi import Depends

from app.auth import require_roles

ADMIN, OPERATOR, VIEWER = 'ADMIN', 'OPERATOR', 'VIEWER'
ALL_ROLES = (ADMIN, OPERATOR, VIEWER)
EDITORS = (ADMIN, OPERATOR)

PERMISSIONS: dict[str, tuple[str, ...]] = {
    'customers:read': ALL_ROLES,
    'customers:write': EDITORS,
    'customers:delete': (ADMIN,),
    'orders:read': ALL_ROLES,
    'orders:write': EDITORS,
    'orders:change-status': EDITORS,
    'ai-results:read': ALL_ROLES,
    'ai-results:write': EDITORS,
    'metrics:read': ALL_ROLES,
}


def require_permission(permission: str):
    """Dependency returning the Principal; raises KeyError at import time for a typo."""
    return require_roles(*PERMISSIONS[permission])


def allow(permission: str) -> list:
    """For `dependencies=` on a route that does not need the Principal object."""
    return [Depends(require_permission(permission))]


def roles_label(permission: str) -> str:
    """Human-readable roles for OpenAPI summaries, e.g. 'ADMIN / OPERATOR'."""
    return ' / '.join(PERMISSIONS[permission])
