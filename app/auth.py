"""Authentication (who are you?) and authorization (may you do this?) dependencies.

Every protected route depends on get_principal through require_roles(...):
  401 - token missing, malformed, wrong signature/algorithm, expired, revoked (logout),
        or the member no longer exists
  403 - token valid but the member's CURRENT role (read from DB) is not allowed
"""
import re
from datetime import datetime, timezone
from typing import Annotated

import jwt
import psycopg
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import get_settings
from app.db import get_connection
from app.models import Principal
from app.security import ALGORITHM

Database = Annotated[psycopg.Connection, Depends(get_connection, scope='function')]
bearer = HTTPBearer(auto_error=False, description='JWT HS256 from POST /api/auth/login. '
                                                  'Claims: sub = member ID (string), exp, jti.')
TOKEN_ID = re.compile(r'^[A-Za-z0-9_-]{1,64}$')
MAX_MEMBER_ID = 9223372036854775807


def unauthorized() -> HTTPException:
    return HTTPException(401, 'Invalid or missing access token', headers={'WWW-Authenticate': 'Bearer'})


def get_principal(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    connection: Database,
) -> Principal:
    if credentials is None:
        raise unauthorized()
    try:
        claims = jwt.decode(credentials.credentials, get_settings().jwt_secret,
                            algorithms=[ALGORITHM], options={'require': ['sub', 'exp', 'jti']})
        subject, token_id = claims['sub'], claims['jti']
        if not isinstance(subject, str) or not subject.isascii() or not subject.isdecimal():
            raise unauthorized()
        if not isinstance(token_id, str) or not TOKEN_ID.match(token_id):
            raise unauthorized()
        member_id = int(subject)
        if not 0 < member_id <= MAX_MEMBER_ID:
            raise unauthorized()
        expires_at = datetime.fromtimestamp(claims['exp'], timezone.utc)
    except (jwt.InvalidTokenError, ValueError, OverflowError, OSError):
        raise unauthorized() from None
    # One round trip: current role + whether this exact token was revoked by logout.
    member = connection.execute(
        '''SELECT m.id, m.role,
                  EXISTS (SELECT 1 FROM revoked_tokens r WHERE r.jti = %s) AS revoked
           FROM members m WHERE m.id = %s''',
        (token_id, member_id),
    ).fetchone()
    if member is None or member['revoked']:
        raise unauthorized()
    return Principal(id=member['id'], role=member['role'], token_id=token_id, token_expires_at=expires_at)


CurrentPrincipal = Annotated[Principal, Depends(get_principal)]


def require_roles(*roles: str):
    def check(principal: CurrentPrincipal) -> Principal:
        if principal.role not in roles:
            raise HTTPException(403, 'Insufficient permissions')
        return principal
    return check
