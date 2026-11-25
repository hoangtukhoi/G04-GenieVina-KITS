from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.auth_api import router as auth_router
from app.config import get_settings
from app.customers import router as customers_router
from app.errors import register_exception_handlers


@asynccontextmanager
async def lifespan(app: FastAPI):
    get_settings()  # Fail startup rather than run with an empty JWT secret.
    yield


DESCRIPTION = '''REST API quản lý dữ liệu và chỉ số vận hành Connext GNOM.

**Cách thử trên Swagger**
1. `POST /api/auth/login` với tài khoản mẫu (`admin@example.invalid` / `operator@example.invalid` /
   `viewer@example.invalid`, mật khẩu `DemoOnly!2026`).
2. Copy `data.accessToken`, bấm **Authorize**, dán token (không cần gõ chữ `Bearer`).
3. Gọi các API khác. `POST /api/auth/logout` thu hồi token hiện tại.

**Phân quyền:** ADMIN quản lý toàn bộ · OPERATOR nhập/sửa dữ liệu, đổi trạng thái đơn · VIEWER chỉ xem và thống kê.

**Định dạng phản hồi chung:** `{"status": <HTTP status>, "message": "...", "data": ...}`.
Mã lỗi: 400 đầu vào sai · 401 thiếu/sai/hết hạn/đã thu hồi token · 403 không đủ quyền ·
404 không tìm thấy · 409 xung đột dữ liệu · 503 database không khả dụng.
'''

TAGS = [
    {'name': 'Auth', 'description': 'Đăng nhập (cấp JWT), đăng xuất (thu hồi JWT), thông tin tài khoản hiện tại'},
    {'name': 'Customers', 'description': 'CRUD khách hàng'},
]

app = FastAPI(title='Genie Vina – Connext GNOM Operations API', version='1.0.0', lifespan=lifespan,
              description=DESCRIPTION, openapi_tags=TAGS,
              swagger_ui_parameters={'persistAuthorization': True})
register_exception_handlers(app)
app.include_router(auth_router)
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
