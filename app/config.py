import os
from dataclasses import dataclass
from functools import lru_cache

DEFAULT_TOKEN_MINUTES = 60


@dataclass(frozen=True)
class Settings:
    database_url: str
    jwt_secret: str
    access_token_minutes: int = DEFAULT_TOKEN_MINUTES


@lru_cache
def get_settings() -> Settings:
    database_url = os.environ.get('DATABASE_URL', '')
    jwt_secret = os.environ.get('JWT_SECRET', '')
    if not database_url:
        raise RuntimeError('DATABASE_URL is required')
    if len(jwt_secret.encode()) < 32:
        raise RuntimeError('JWT_SECRET must contain at least 32 bytes')
    raw_minutes = os.environ.get('JWT_EXPIRES_MINUTES', '') or str(DEFAULT_TOKEN_MINUTES)
    if not raw_minutes.isdecimal() or not 5 <= int(raw_minutes) <= 1440:
        raise RuntimeError('JWT_EXPIRES_MINUTES must be an integer between 5 and 1440')
    return Settings(database_url, jwt_secret, int(raw_minutes))
