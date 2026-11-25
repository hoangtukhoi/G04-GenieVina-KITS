"""HTTP tests for login / logout / me against the seeded PostgreSQL schema.

Seed accounts (scripts/generate_seed.py): 1 ADMIN, 2 OPERATOR, 3 VIEWER, password DemoOnly!2026.
"""
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import jwt
import psycopg
import pytest

from tests.conftest import TEST_SECRET
from tests.test_customers_api import assert_response, auth, body

PASSWORD = 'DemoOnly!2026'
ACCOUNTS = {'admin@example.invalid': 'ADMIN', 'operator@example.invalid': 'OPERATOR',
            'viewer@example.invalid': 'VIEWER'}


def login(client, email, password=PASSWORD):
    return client.post('/api/auth/login', json={'email': email, 'password': password})


def bearer(token):
    return {'Authorization': f'Bearer {token}'}


@pytest.mark.parametrize('email,role', ACCOUNTS.items())
def test_login_returns_token_and_member_profile(client, email, role):
    data = assert_response(login(client, email), 200)
    assert data['tokenType'] == 'Bearer'
    assert data['expiresIn'] == 3600
    assert data['member']['email'] == email and data['member']['role'] == role
    assert set(data['member']) == {'id', 'email', 'name', 'role'}  # never password_hash
    claims = jwt.decode(data['accessToken'], TEST_SECRET, algorithms=['HS256'])
    assert claims['sub'] == str(data['member']['id'])
    assert 'role' not in claims


def test_login_email_is_case_insensitive_and_trimmed(client):
    assert_response(login(client, '  ADMIN@Example.INVALID '), 200)


@pytest.mark.parametrize('email,password', [
    ('admin@example.invalid', 'wrong-password'),
    ('admin@example.invalid', 'demoonly!2026'),
    ('nobody@example.invalid', PASSWORD),
])
def test_wrong_credentials_give_same_401(client, email, password):
    response = login(client, email, password)
    assert_response(response, 401)
    assert response.json()['message'] == 'Invalid email or password'
    assert PASSWORD not in response.text and 'password_hash' not in response.text


@pytest.mark.parametrize('payload', [
    {}, {'email': 'admin@example.invalid'}, {'password': PASSWORD},
    {'email': 'not-an-email', 'password': PASSWORD}, {'email': 'admin@example.invalid', 'password': ''},
    {'email': 'admin@example.invalid', 'password': 'x' * 129},
    {'email': 'admin@example.invalid', 'password': PASSWORD, 'role': 'ADMIN'},
])
def test_login_validation_returns_400_without_echoing_password(client, payload):
    response = client.post('/api/auth/login', json=payload)
    assert_response(response, 400)
    assert PASSWORD not in response.text


def test_member_with_unusable_hash_cannot_log_in(client, api_database):
    email = uuid4().hex + '@example.invalid'
    with psycopg.connect(api_database) as connection:
        connection.execute("INSERT INTO members(email, password_hash, name, role) VALUES (%s, 'unused', 'T', 'ADMIN')",
                           (email,))
    assert_response(login(client, email, 'unused'), 401)


def test_login_token_works_with_role_permissions(client):
    viewer = bearer(assert_response(login(client, 'viewer@example.invalid'), 200)['accessToken'])
    operator = bearer(assert_response(login(client, 'operator@example.invalid'), 200)['accessToken'])
    assert_response(client.get('/api/customers', headers=viewer), 200)
    assert_response(client.post('/api/customers', json=body(), headers=viewer), 403)
    assert_response(client.post('/api/customers', json=body(), headers=operator), 201)
    assert_response(client.delete('/api/customers/1', headers=operator), 403)


def test_me_returns_current_member(client):
    token = assert_response(login(client, 'operator@example.invalid'), 200)['accessToken']
    me = assert_response(client.get('/api/auth/me', headers=bearer(token)), 200)
    assert me == {'id': 2, 'email': 'operator@example.invalid', 'name': 'Demo OPERATOR', 'role': 'OPERATOR'}
    assert_response(client.get('/api/auth/me'), 401)


def test_logout_revokes_only_that_token(client, api_database):
    first = assert_response(login(client, 'admin@example.invalid'), 200)['accessToken']
    second = assert_response(login(client, 'admin@example.invalid'), 200)['accessToken']
    assert_response(client.post('/api/auth/logout', headers=bearer(first)), 200)
    # The logged-out token is rejected everywhere, including a second logout.
    assert_response(client.get('/api/customers', headers=bearer(first)), 401)
    assert_response(client.post('/api/auth/logout', headers=bearer(first)), 401)
    # Another session of the same member keeps working.
    assert_response(client.get('/api/customers', headers=bearer(second)), 200)
    jti = jwt.decode(first, TEST_SECRET, algorithms=['HS256'])['jti']
    with psycopg.connect(api_database) as connection:
        row = connection.execute('SELECT member_id, expires_at FROM revoked_tokens WHERE jti = %s', (jti,)).fetchone()
    assert row[0] == 1 and row[1] > datetime.now(timezone.utc)


def test_logout_requires_a_valid_token(client):
    assert_response(client.post('/api/auth/logout'), 401)
    assert_response(client.post('/api/auth/logout', headers=bearer('not-a-jwt')), 401)


def test_logout_cleans_up_expired_denylist_rows(client, api_database):
    with psycopg.connect(api_database) as connection:
        connection.execute("INSERT INTO revoked_tokens(jti, member_id, expires_at) VALUES ('old-token', 1, now() - interval '1 hour')")
    assert_response(client.post('/api/auth/logout', headers=auth(3)), 200)
    with psycopg.connect(api_database) as connection:
        assert connection.execute("SELECT COUNT(*) FROM revoked_tokens WHERE jti = 'old-token'").fetchone()[0] == 0


def test_token_without_jti_is_rejected(client):
    token = jwt.encode({'sub': '1', 'exp': datetime.now(timezone.utc) + timedelta(minutes=5)}, TEST_SECRET, algorithm='HS256')
    assert_response(client.get('/api/customers', headers=bearer(token)), 401)


def test_role_change_applies_to_existing_token_immediately(client, api_database):
    email = uuid4().hex + '@example.invalid'
    from app.security import hash_password
    with psycopg.connect(api_database) as connection:
        mid = connection.execute('INSERT INTO members(email, password_hash, name, role) VALUES (%s, %s, %s, %s) RETURNING id',
                                 (email, hash_password(PASSWORD, iterations=1000), 'T', 'OPERATOR')).fetchone()[0]
    token = bearer(assert_response(login(client, email), 200)['accessToken'])
    assert_response(client.post('/api/customers', json=body(), headers=token), 201)
    with psycopg.connect(api_database) as connection:
        connection.execute("UPDATE members SET role = 'VIEWER' WHERE id = %s", (mid,))
    assert_response(client.post('/api/customers', json=body(), headers=token), 403)
    with psycopg.connect(api_database) as connection:
        connection.execute('DELETE FROM revoked_tokens WHERE member_id = %s', (mid,))
        connection.execute('DELETE FROM members WHERE id = %s', (mid,))
    assert_response(client.get('/api/customers', headers=token), 401)
