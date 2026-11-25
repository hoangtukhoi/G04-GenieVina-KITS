"""Password verification and access-token issuing.

Password hashes use the format written by scripts/generate_seed.py (Django-compatible):
    pbkdf2_sha256$<iterations>$<salt>$<base64 digest>
Only the standard library is needed, so no extra dependency is introduced.
"""
import base64
import binascii
import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from uuid import uuid4

import jwt

from app.config import Settings

ALGORITHM = 'HS256'
HASH_SCHEME = 'pbkdf2_sha256'
DEFAULT_ITERATIONS = 600_000
# Upper bound protects the server from a corrupted/hostile hash that would burn CPU forever.
MAX_ITERATIONS = 5_000_000


def hash_password(password: str, *, salt: str | None = None, iterations: int = DEFAULT_ITERATIONS) -> str:
    salt = salt or secrets.token_urlsafe(16)
    if '$' in salt:
        raise ValueError('Salt must not contain "$"')
    digest = hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), iterations)
    return f'{HASH_SCHEME}${iterations}${salt}${base64.b64encode(digest).decode()}'


def verify_password(password: str, encoded: str) -> bool:
    """Constant-time check. Malformed or unknown hashes simply fail (never raise)."""
    try:
        scheme, raw_iterations, salt, expected_b64 = encoded.split('$')
        if scheme != HASH_SCHEME or not raw_iterations.isdecimal():
            return False
        iterations = int(raw_iterations)
        if not 1 <= iterations <= MAX_ITERATIONS:
            return False
        expected = base64.b64decode(expected_b64, validate=True)
    except (ValueError, binascii.Error):
        return False
    actual = hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), iterations)
    return hmac.compare_digest(actual, expected)


@lru_cache
def dummy_hash() -> str:
    """Verified when the email does not exist so the response time does not reveal it."""
    return hash_password(secrets.token_urlsafe(16))


def create_access_token(member_id: int, settings: Settings, *, now: datetime | None = None) -> tuple[str, datetime]:
    now = now or datetime.now(timezone.utc)
    expires_at = now + timedelta(minutes=settings.access_token_minutes)
    claims = {
        'sub': str(member_id),  # Role is NOT put in the token: it is read from DB on each request.
        'iat': now,
        'exp': expires_at,
        'jti': uuid4().hex,     # Unique token ID, needed to revoke this one token on logout.
    }
    return jwt.encode(claims, settings.jwt_secret, algorithm=ALGORITHM), expires_at
