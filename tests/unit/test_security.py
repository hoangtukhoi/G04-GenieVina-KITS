import base64
import hashlib
from datetime import datetime, timezone

import jwt
import pytest

from app.config import Settings
from app.security import ALGORITHM, create_access_token, dummy_hash, hash_password, verify_password

SECRET = 'unit-test-secret-at-least-32-bytes-long'


def seed_style_hash(password, salt='genie-demo-salt-1', iterations=1000):
    """Same construction as scripts/generate_seed.py (fewer iterations to keep tests fast)."""
    digest = base64.b64encode(hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), iterations)).decode()
    return f'pbkdf2_sha256${iterations}${salt}${digest}'


def test_hash_and_verify_round_trip():
    encoded = hash_password('Correct horse', iterations=1000)
    assert encoded.startswith('pbkdf2_sha256$1000$')
    assert verify_password('Correct horse', encoded)
    assert not verify_password('correct horse', encoded)
    assert hash_password('same', iterations=1000) != hash_password('same', iterations=1000)  # random salt


def test_accepts_hashes_generated_by_seed_script():
    assert verify_password('DemoOnly!2026', seed_style_hash('DemoOnly!2026'))
    assert not verify_password('DemoOnly!2027', seed_style_hash('DemoOnly!2026'))


@pytest.mark.parametrize('encoded', [
    '', 'unused', 'DemoOnly!2026',
    'md5$1000$salt$abc',
    'pbkdf2_sha256$abc$salt$AAAA',
    'pbkdf2_sha256$0$salt$AAAA',
    'pbkdf2_sha256$999999999$salt$AAAA',
    'pbkdf2_sha256$1000$salt$not base64!',
    'pbkdf2_sha256$1000$salt$AAAA$extra',
])
def test_malformed_hashes_fail_closed_without_raising(encoded):
    assert verify_password('DemoOnly!2026', encoded) is False


def test_dummy_hash_has_production_cost_and_matches_nothing_guessable():
    assert dummy_hash().startswith('pbkdf2_sha256$600000$')
    assert not verify_password('', dummy_hash())
    assert not verify_password('DemoOnly!2026', dummy_hash())


def test_access_token_claims():
    now = datetime(2026, 1, 1, 9, 0, tzinfo=timezone.utc)
    token, expires_at = create_access_token(7, Settings('unused', SECRET, 60), now=now)
    claims = jwt.decode(token, SECRET, algorithms=[ALGORITHM], options={'verify_exp': False})
    assert claims['sub'] == '7'
    assert claims['exp'] - claims['iat'] == 3600
    assert expires_at == datetime(2026, 1, 1, 10, 0, tzinfo=timezone.utc)
    assert len(claims['jti']) == 32
    assert 'role' not in claims and 'email' not in claims
    assert jwt.get_unverified_header(token)['alg'] == 'HS256'


def test_each_token_gets_a_unique_id():
    settings = Settings('unused', SECRET)
    ids = {jwt.decode(create_access_token(1, settings)[0], SECRET, algorithms=[ALGORITHM])['jti'] for _ in range(20)}
    assert len(ids) == 20
