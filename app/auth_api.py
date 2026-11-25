"""POST /api/auth/login, POST /api/auth/logout, GET /api/auth/me."""
import logging

from fastapi import APIRouter

from app.auth import CurrentPrincipal, Database
from app.config import get_settings
from app.errors import AppError, error_responses, ok
from app.models import Envelope, LoginData, LoginRequest, MemberOut
from app.security import create_access_token, dummy_hash, verify_password

logger = logging.getLogger(__name__)
router = APIRouter(prefix='/api/auth', tags=['Auth'])

# Same message for unknown email and wrong password: do not reveal which accounts exist.
INVALID_CREDENTIALS = 'Invalid email or password'


@router.post('/login', response_model=Envelope[LoginData],
             responses=error_responses({401: INVALID_CREDENTIALS}, public=True),
             summary='Log in and receive a JWT access token (public)')
def login(body: LoginRequest, connection: Database):
    member = connection.execute(
        'SELECT id, email, name, role, password_hash FROM members WHERE LOWER(email) = LOWER(%s)',
        (body.email,),
    ).fetchone()
    # Always run one PBKDF2 verification so timing does not reveal whether the email exists.
    valid = verify_password(body.password, member['password_hash'] if member else dummy_hash())
    if member is None or not valid:
        logger.info('Failed login attempt')  # No email/password in logs.
        raise AppError(401, INVALID_CREDENTIALS, headers={'WWW-Authenticate': 'Bearer'})
    settings = get_settings()
    token, expires_at = create_access_token(member['id'], settings)
    return ok({
        'accessToken': token,
        'tokenType': 'Bearer',
        'expiresIn': settings.access_token_minutes * 60,
        'expiresAt': expires_at,
        'member': {key: member[key] for key in ('id', 'email', 'name', 'role')},
    })


@router.post('/logout', response_model=Envelope[None], responses=error_responses(),
             summary='Revoke the current access token (all roles)')
def logout(principal: CurrentPrincipal, connection: Database):
    # JWTs are stateless, so logout stores this token's jti in a denylist that
    # get_principal checks. Only THIS token is revoked; other sessions stay valid.
    connection.execute(
        '''INSERT INTO revoked_tokens(jti, member_id, expires_at) VALUES (%s, %s, %s)
           ON CONFLICT (jti) DO NOTHING''',
        (principal.token_id, principal.id, principal.token_expires_at),
    )
    # Housekeeping: an expired token is rejected by its exp claim anyway, so its row is useless.
    connection.execute('DELETE FROM revoked_tokens WHERE expires_at < CURRENT_TIMESTAMP')
    return ok(None, message='Logged out')


@router.get('/me', response_model=Envelope[MemberOut], responses=error_responses(),
            summary='Current member profile and role (all roles)')
def me(principal: CurrentPrincipal, connection: Database):
    member = connection.execute('SELECT id, email, name, role FROM members WHERE id = %s',
                                (principal.id,)).fetchone()
    return ok(member)
