"""Common response envelope and exception handling shared by every router.

Every response, success or error, has the shape {"status", "message", "data"} and the
body status always equals the HTTP status. Routers raise AppError (or HTTPException)
for business errors; database constraint violations are translated here by constraint
name so that each module gets its own message instead of a generic one.
"""
import logging
from typing import Any

import psycopg
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

from app.models import ErrorEnvelope

logger = logging.getLogger(__name__)


class AppError(Exception):
    """Business error raised by services/routers; rendered with the common envelope."""

    def __init__(self, status: int, message: str, data: Any = None, headers: dict[str, str] | None = None):
        super().__init__(message)
        self.status = status
        self.message = message
        self.data = data
        self.headers = headers


def ok(data: Any = None, status: int = 200, message: str = 'success') -> dict:
    """Success body. Return it from a route declared with response_model=Envelope[...]."""
    return {'status': status, 'message': message, 'data': data}


def error_response(status: int, message: str, data: Any = None, headers: dict[str, str] | None = None):
    return JSONResponse(status_code=status, content={'status': status, 'message': message, 'data': data},
                        headers=headers)


# Constraint name -> (HTTP status, client message). Names come from database/schema.sql:
# table constraints use PostgreSQL defaults, trigger errors set USING CONSTRAINT = '...'.
CONSTRAINT_ERRORS: dict[str, tuple[int, str]] = {
    # customers
    'customers_customer_code_key': (409, 'Customer code already exists'),
    'orders_customer_id_fkey': (409, 'Customer has related orders or AI results and cannot be deleted'),
    'ai_results_customer_id_fkey': (409, 'Customer has related orders or AI results and cannot be deleted'),
    'customers_signup_before_events': (409, 'Customer signup date conflicts with existing events'),
    # orders / AI results written for a customer
    'customer_event_customer_exists': (404, 'Customer not found'),
    'customer_event_after_signup': (400, 'Event time cannot be earlier than customer signup'),
    'orders_amount_check': (400, 'Amount must be greater than 0'),
    'orders_initial_status': (400, 'New orders must start as PENDING'),
    'orders_immutable_fields': (409, 'Order customer and creation time cannot be changed'),
    'orders_payment_time_immutable': (409, 'Existing payment time cannot be changed'),
    'orders_refund_time_immutable': (409, 'Existing refund time cannot be changed'),
    'orders_valid_transition': (409, 'Invalid order status transition'),
    'orders_payment_times': (409, 'Payment/refund time does not match order status'),
    # members
    'members_email_unique': (409, 'Email already exists'),
}

# Fallback by SQLSTATE class when a constraint is not registered above.
GENERIC_INTEGRITY_ERRORS: list[tuple[type[psycopg.Error], tuple[int, str]]] = [
    (psycopg.errors.UniqueViolation, (409, 'Resource already exists')),
    (psycopg.errors.ForeignKeyViolation, (409, 'Related data conflict')),
    (psycopg.errors.CheckViolation, (409, 'Data violates a business rule')),
]


async def app_error(request: Request, exc: AppError):
    return error_response(exc.status, exc.message, exc.data, exc.headers)


async def http_error(request: Request, exc: HTTPException):
    # Covers raise HTTPException(...) in routers plus Starlette's own 404/405.
    return error_response(exc.status_code, str(exc.detail), headers=exc.headers)


async def validation_error(request: Request, exc: RequestValidationError):
    # Do not echo raw request bodies or sensitive input (passwords) in validation errors.
    issues = [{'field': '.'.join(map(str, issue['loc'])), 'message': issue['msg']} for issue in exc.errors()]
    return error_response(400, 'Invalid input', {'errors': issues})


async def database_error(request: Request, exc: psycopg.Error):
    constraint = getattr(getattr(exc, 'diag', None), 'constraint_name', None)
    if constraint in CONSTRAINT_ERRORS:
        return error_response(*CONSTRAINT_ERRORS[constraint])
    for error_type, (status, message) in GENERIC_INTEGRITY_ERRORS:
        if isinstance(exc, error_type):
            logger.warning('Unmapped constraint violation (SQLSTATE=%s, constraint=%s)', exc.sqlstate, constraint)
            return error_response(status, message)
    if isinstance(exc, (psycopg.OperationalError, psycopg.InterfaceError)):
        logger.error('Database unavailable: %s', type(exc).__name__)
        return error_response(503, 'Database unavailable')
    logger.error('Database operation failed (SQLSTATE=%s)', exc.sqlstate)
    return error_response(500, 'Internal server error')


async def unexpected_error(request: Request, exc: Exception):
    # Never leak exception text or stack traces to the client or the log message.
    logger.error('Unhandled API error: %s', type(exc).__name__)
    return error_response(500, 'Internal server error')


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, app_error)
    app.add_exception_handler(HTTPException, http_error)
    app.add_exception_handler(RequestValidationError, validation_error)
    app.add_exception_handler(psycopg.Error, database_error)
    app.add_exception_handler(Exception, unexpected_error)


DEFAULT_ERROR_DESCRIPTIONS = {
    400: 'Invalid input',
    401: 'Missing, invalid, expired or revoked access token',
    403: 'Insufficient permissions',
    503: 'Database unavailable',
}


def error_responses(extra: dict[int, str] | None = None, *, public: bool = False) -> dict:
    """OpenAPI `responses` for a router/route, all documented with the common error envelope.

    public=True drops 401/403 for endpoints that do not require a token (login).
    """
    descriptions = dict(DEFAULT_ERROR_DESCRIPTIONS)
    if public:
        descriptions.pop(401)
        descriptions.pop(403)
    descriptions.update(extra or {})
    return {code: {'model': ErrorEnvelope, 'description': text} for code, text in sorted(descriptions.items())}
