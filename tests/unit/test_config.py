import pytest

from app.config import get_settings


@pytest.fixture(autouse=True)
def isolated_settings(monkeypatch):
    get_settings.cache_clear()
    monkeypatch.delenv('DATABASE_URL', raising=False)
    monkeypatch.delenv('JWT_SECRET', raising=False)
    monkeypatch.delenv('JWT_EXPIRES_MINUTES', raising=False)
    yield
    get_settings.cache_clear()


def test_database_url_is_required(monkeypatch):
    monkeypatch.setenv('JWT_SECRET', 'X' * 32)
    with pytest.raises(RuntimeError, match='DATABASE_URL is required'):
        get_settings()


@pytest.mark.parametrize('secret', ['', 'X' * 31])
def test_missing_or_short_signing_secret_prevents_startup(monkeypatch, secret):
    monkeypatch.setenv('DATABASE_URL', 'postgresql://localhost/test')
    monkeypatch.setenv('JWT_SECRET', secret)
    with pytest.raises(RuntimeError, match='at least 32 bytes'):
        get_settings()


def test_minimum_length_signing_secret_is_accepted(monkeypatch):
    monkeypatch.setenv('DATABASE_URL', 'postgresql://localhost/test')
    monkeypatch.setenv('JWT_SECRET', 'X' * 32)
    settings = get_settings()
    assert settings.database_url == 'postgresql://localhost/test'
    assert settings.jwt_secret == 'X' * 32


@pytest.fixture
def valid_env(monkeypatch):
    monkeypatch.setenv('DATABASE_URL', 'postgresql://localhost/test')
    monkeypatch.setenv('JWT_SECRET', 'X' * 32)


def test_token_lifetime_defaults_to_60_minutes(valid_env):
    assert get_settings().access_token_minutes == 60


def test_token_lifetime_can_be_configured(valid_env, monkeypatch):
    monkeypatch.setenv('JWT_EXPIRES_MINUTES', '15')
    assert get_settings().access_token_minutes == 15


@pytest.mark.parametrize('value', ['0', '4', '1441', '-5', 'abc', '1.5'])
def test_invalid_token_lifetime_prevents_startup(valid_env, monkeypatch, value):
    monkeypatch.setenv('JWT_EXPIRES_MINUTES', value)
    with pytest.raises(RuntimeError, match='JWT_EXPIRES_MINUTES'):
        get_settings()
