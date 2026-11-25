from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import get_settings
from app.customers import router as customers_router
from app.errors import register_exception_handlers


@asynccontextmanager
async def lifespan(app: FastAPI):
    get_settings()  # Fail startup rather than run with an empty JWT secret.
    yield


app = FastAPI(title='Genie Vina – Connext GNOM Operations API', version='1.0.0', lifespan=lifespan,
              description='REST API quản lý dữ liệu và chỉ số vận hành Connext GNOM. Bearer JWT; '
                          'vai trò ADMIN / OPERATOR / VIEWER. Mọi phản hồi có dạng '
                          '`{"status", "message", "data"}`.')
register_exception_handlers(app)
app.include_router(customers_router)


# Validation errors are normalized to HTTP 400 (app.errors.validation_error), so drop the
# 422 response FastAPI adds to every operation to keep the OpenAPI document truthful.
original_openapi = app.openapi


def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema
    schema = original_openapi()
    for operations in schema['paths'].values():
        for operation in operations.values():
            if isinstance(operation, dict):
                operation.get('responses', {}).pop('422', None)
    schema.get('components', {}).get('schemas', {}).pop('HTTPValidationError', None)
    schema.get('components', {}).get('schemas', {}).pop('ValidationError', None)
    app.openapi_schema = schema
    return schema


app.openapi = custom_openapi
