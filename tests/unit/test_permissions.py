"""The permission matrix must match the assignment: ADMIN all / OPERATOR edit data and
order status / VIEWER read data and metrics only."""
import pytest
from fastapi import HTTPException

from app.models import Principal
from app.permissions import PERMISSIONS, require_permission, roles_label

EXPECTED = {
    #                       ADMIN  OPERATOR VIEWER
    'customers:read':       (True, True, True),
    'customers:write':      (True, True, False),
    'customers:delete':     (True, False, False),
    'orders:read':          (True, True, True),
    'orders:write':         (True, True, False),
    'orders:change-status': (True, True, False),
    'ai-results:read':      (True, True, True),
    'ai-results:write':     (True, True, False),
    'metrics:read':         (True, True, True),
}


def test_matrix_covers_exactly_the_expected_permissions():
    assert set(PERMISSIONS) == set(EXPECTED)


@pytest.mark.parametrize('permission', EXPECTED)
@pytest.mark.parametrize('index,role', list(enumerate(['ADMIN', 'OPERATOR', 'VIEWER'])))
def test_permission_matrix(permission, index, role):
    principal = Principal(id=1, role=role)
    check = require_permission(permission)
    if EXPECTED[permission][index]:
        assert check(principal) == principal
    else:
        with pytest.raises(HTTPException) as exc:
            check(principal)
        assert exc.value.status_code == 403


def test_admin_has_every_permission_and_viewer_never_writes():
    assert all('ADMIN' in roles for roles in PERMISSIONS.values())
    assert all(name.endswith(':read') for name, roles in PERMISSIONS.items() if 'VIEWER' in roles)


def test_unknown_permission_fails_fast():
    with pytest.raises(KeyError):
        require_permission('orders:wirte')


def test_roles_label():
    assert roles_label('customers:delete') == 'ADMIN'
    assert roles_label('orders:write') == 'ADMIN / OPERATOR'
