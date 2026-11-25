import asyncio
import json

import psycopg
import pytest
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException
from starlette.requests import Request

from app.errors import (
    AppError, app_error, database_error, error_responses, http_error, ok, unexpected_error, validation_error,
)

REQUEST = Request({'type': 'http', 'method': 'GET', 'path': '/api/customers', 'headers': []})
PRIVATE = 'private-database-password-and-query-details'


def response_body(response, status):
    assert response.status_code == status
    body = json.loads(response.body)
    assert set(body) == {'status', 'message', 'data'}
    assert body['status'] == status
    return body


@pytest.mark.parametrize('exception_type,status', [
    (psycopg.errors.UniqueViolation, 409),
    (psycopg.errors.ForeignKeyViolation, 409),
    (psycopg.errors.CheckViolation, 409),
    (psycopg.OperationalError, 503),
    (psycopg.InterfaceError, 503),
    (psycopg.errors.UndefinedTable, 500),
])
def test_database_errors_are_normalized_without_exposing_details(exception_type, status, caplog):
    response = asyncio.run(database_error(REQUEST, exception_type(PRIVATE)))
    body = response_body(response, status)
    assert body['data'] is None
    assert PRIVATE not in response.body.decode()
    assert PRIVATE not in caplog.text


def test_authentication_error_preserves_bearer_challenge():
    response = asyncio.run(http_error(REQUEST, HTTPException(
        401, 'Invalid access token', headers={'WWW-Authenticate': 'Bearer'})))
    assert response_body(response, 401)['message'] == 'Invalid access token'
    assert response.headers['www-authenticate'] == 'Bearer'


def test_validation_error_returns_field_path_without_raw_input_or_context():
    exc = RequestValidationError([{
        'loc': ('body', 'customerCode'), 'msg': 'String should have at most 40 characters',
        'type': 'string_too_long', 'input': PRIVATE, 'ctx': {'private': PRIVATE},
    }], body={'customerCode': PRIVATE})
    response = asyncio.run(validation_error(REQUEST, exc))
    body = response_body(response, 400)
    assert body['data']['errors'] == [{
        'field': 'body.customerCode', 'message': 'String should have at most 40 characters',
    }]
    assert PRIVATE not in response.body.decode()


def test_unexpected_error_does_not_leak_exception_text(caplog):
    response = asyncio.run(unexpected_error(REQUEST, RuntimeError(PRIVATE)))
    assert response_body(response, 500)['message'] == 'Internal server error'
    assert PRIVATE not in response.body.decode()
    assert PRIVATE not in caplog.text


class FakeDiag:
    def __init__(self, constraint_name):
        self.constraint_name = constraint_name


def violation(error_type, constraint):
    exc = error_type(PRIVATE)
    # psycopg exposes diagnostics read-only; patch the attribute on a subclass instance.
    exc.__class__ = type(error_type.__name__, (error_type,), {'diag': FakeDiag(constraint)})
    return exc


@pytest.mark.parametrize('error_type,constraint,status,message', [
    (psycopg.errors.UniqueViolation, 'customers_customer_code_key', 409, 'Customer code already exists'),
    (psycopg.errors.ForeignKeyViolation, 'orders_customer_id_fkey', 409,
     'Customer has related orders or AI results and cannot be deleted'),
    (psycopg.errors.ForeignKeyViolation, 'customer_event_customer_exists', 404, 'Customer not found'),
    (psycopg.errors.CheckViolation, 'orders_valid_transition', 409, 'Invalid order status transition'),
    (psycopg.errors.CheckViolation, 'orders_amount_check', 400, 'Amount must be greater than 0'),
    (psycopg.errors.UniqueViolation, 'members_email_unique', 409, 'Email already exists'),
])
def test_constraint_violations_map_to_module_specific_messages(error_type, constraint, status, message):
    response = asyncio.run(database_error(REQUEST, violation(error_type, constraint)))
    assert response_body(response, status)['message'] == message
    assert PRIVATE not in response.body.decode()


@pytest.mark.parametrize('error_type,message', [
    (psycopg.errors.UniqueViolation, 'Resource already exists'),
    (psycopg.errors.ForeignKeyViolation, 'Related data conflict'),
    (psycopg.errors.CheckViolation, 'Data violates a business rule'),
])
def test_unmapped_constraints_fall_back_to_generic_conflict(error_type, message):
    response = asyncio.run(database_error(REQUEST, violation(error_type, 'some_future_constraint')))
    assert response_body(response, 409)['message'] == message


def test_app_error_renders_common_envelope_with_data():
    response = asyncio.run(app_error(REQUEST, AppError(409, 'Insufficient stock', {'ids': [1, 2]})))
    assert response_body(response, 409) == {'status': 409, 'message': 'Insufficient stock', 'data': {'ids': [1, 2]}}


def test_ok_helper_builds_success_envelope():
    assert ok({'id': 1}, 201) == {'status': 201, 'message': 'success', 'data': {'id': 1}}
    assert ok() == {'status': 200, 'message': 'success', 'data': None}


def test_error_responses_document_common_codes():
    responses = error_responses({404: 'Order not found'})
    assert set(responses) == {400, 401, 403, 404, 503}
    assert set(error_responses(public=True)) == {400, 503}
