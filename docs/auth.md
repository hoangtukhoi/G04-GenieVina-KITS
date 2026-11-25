# Phần D – Xác thực, phân quyền, phản hồi chung, xử lý ngoại lệ, Swagger

## 1. Endpoint

| Method | Endpoint | Quyền | Thành công | Lỗi |
|---|---|---|---|---|
| POST | `/api/auth/login` | Công khai | 200 + JWT | 400 đầu vào sai · 401 sai email/mật khẩu |
| POST | `/api/auth/logout` | Mọi vai trò đã đăng nhập | 200, `data: null` | 401 |
| GET | `/api/auth/me` | Mọi vai trò đã đăng nhập | 200 + thông tin tài khoản | 401 |

Login:

```json
// Request
{ "email": "admin@example.invalid", "password": "DemoOnly!2026" }

// 200
{
  "status": 200, "message": "success",
  "data": {
    "accessToken": "eyJhbGciOiJIUzI1NiIs...",
    "tokenType": "Bearer",
    "expiresIn": 3600,
    "expiresAt": "2026-11-25T10:00:00Z",
    "member": { "id": 1, "email": "admin@example.invalid", "name": "Demo ADMIN", "role": "ADMIN" }
  }
}

// 401 (sai email HOẶC sai mật khẩu: cùng một thông báo)
{ "status": 401, "message": "Invalid email or password", "data": null }
```

Gọi API khác bằng header `Authorization: Bearer <accessToken>`. Trên Swagger: bấm **Authorize**, dán token.

## 2. Luồng token

```mermaid
sequenceDiagram
    participant C as Client
    participant A as API
    participant DB as PostgreSQL
    C->>A: POST /api/auth/login {email, password}
    A->>DB: SELECT member WHERE LOWER(email) = LOWER(:email)
    A->>A: PBKDF2 verify (email không tồn tại → verify dummy hash)
    A-->>C: 200 {accessToken (sub, iat, exp, jti)}
    C->>A: GET /api/customers + Bearer token
    A->>A: Verify chữ ký HS256, exp, sub, jti
    A->>DB: SELECT role, revoked(jti) FROM members WHERE id = sub
    A-->>C: 200 / 401 (token sai, hết hạn, đã logout) / 403 (role không đủ)
    C->>A: POST /api/auth/logout + Bearer token
    A->>DB: INSERT revoked_tokens(jti, member_id, expires_at)
    A-->>C: 200; token này từ nay bị 401
```

Claims của JWT: `sub` (member ID dạng chuỗi), `iat`, `exp` (mặc định 60 phút, đổi bằng `JWT_EXPIRES_MINUTES` trong khoảng 5–1440), `jti` (ID ngẫu nhiên của token). **Token không chứa role.**

## 3. Ma trận phân quyền

Nguồn duy nhất: [`app/permissions.py`](../app/permissions.py). Unit test [`tests/unit/test_permissions.py`](../tests/unit/test_permissions.py) khóa ma trận này.

| Quyền | ADMIN | OPERATOR | VIEWER |
|---|:-:|:-:|:-:|
| `customers:read`: xem khách hàng | ✓ | ✓ | ✓ |
| `customers:write`: tạo, sửa khách hàng | ✓ | ✓ | ✗ |
| `customers:delete`: xóa khách hàng | ✓ | ✗ | ✗ |
| `orders:read`: xem đơn, lịch sử trạng thái | ✓ | ✓ | ✓ |
| `orders:write`: tạo đơn | ✓ | ✓ | ✗ |
| `orders:change-status`: đổi trạng thái đơn | ✓ | ✓ | ✗ |
| `ai-results:read`: tra cứu kết quả AI | ✓ | ✓ | ✓ |
| `ai-results:write`: ghi nhận kết quả AI | ✓ | ✓ | ✗ |
| `metrics:read`: thống kê | ✓ | ✓ | ✓ |
| Logout, xem `/me` | ✓ | ✓ | ✓ |

Theo đề: ADMIN quản lý toàn bộ, OPERATOR nhập/sửa dữ liệu và đổi trạng thái đơn, VIEWER chỉ xem và thống kê. Xóa khách là thao tác không hoàn tác nên chỉ ADMIN được làm.

## 4. 401 hay 403?

| Tình huống | Mã |
|---|---|
| Không có header / không phải `Bearer` / token hỏng | 401 |
| Sai chữ ký, sai thuật toán (`none`, HS384...), thiếu `sub`/`exp`/`jti` | 401 |
| Token hết hạn hoặc đã logout | 401 |
| Thành viên đã bị xóa khỏi `members` | 401 |
| Token hợp lệ nhưng vai trò **hiện tại** trong DB không đủ quyền | 403 |

401 kèm header `WWW-Authenticate: Bearer`.

## 5. Định dạng phản hồi và xử lý ngoại lệ

Mọi phản hồi, kể cả lỗi 404 do sai đường dẫn hay 405 do sai method, đều có dạng `{"status", "message", "data"}`, và `status` trong body luôn trùng HTTP status. Code nằm trong [`app/errors.py`](../app/errors.py).

| Nguồn lỗi | Kết quả |
|---|---|
| `raise AppError(status, message, data)` | Đúng status/message/data đã truyền |
| `raise HTTPException(...)`, route không tồn tại, sai method | Status tương ứng, message của exception |
| Validation (body/query/path sai) | **400** `Invalid input`, `data.errors = [{field, message}]`, không trả lại giá trị người dùng gửi (tránh lộ mật khẩu) |
| Vi phạm ràng buộc DB | Tra **tên constraint** trong `CONSTRAINT_ERRORS`, ví dụ `customers_customer_code_key` → 409 `Customer code already exists`, `orders_valid_transition` → 409 `Invalid order status transition` |
| Constraint chưa đăng ký | 409 chung: `Resource already exists` / `Related data conflict` / `Data violates a business rule` |
| Mất kết nối DB | 503 `Database unavailable` |
| Lỗi bất ngờ | 500 `Internal server error`, không trả stacktrace và không log nội dung exception |

Lỗi ném ra từ trigger cũng có tên constraint (`RAISE ... USING CONSTRAINT = '...'` trong `schema.sql`), nhờ vậy lỗi của orders không bị trả về câu thông báo của customers.

## 6. Quyết định thiết kế và phương án bị loại

| Quyết định | Lý do | Phương án bị loại |
|---|---|---|
| Đọc role từ DB mỗi request, không đưa role vào JWT | Đổi hoặc hạ quyền có hiệu lực ngay, không phải chờ token hết hạn | Role trong token: nhanh hơn một chút nhưng giữ quyền cũ tới 60 phút |
| Logout = lưu `jti` vào `revoked_tokens` | Chỉ thu hồi đúng phiên đó, các phiên khác của cùng tài khoản vẫn dùng được | Cột `token_version` trên `members`: logout sẽ đăng xuất mọi thiết bị · Chỉ xóa token phía client: token vẫn dùng được nếu bị lộ |
| Dọn `revoked_tokens` khi logout (`expires_at < now`) | Token hết hạn đã bị chặn bởi `exp`, nên dòng trong bảng không còn tác dụng. Bảng chỉ chứa token chưa hết hạn | Cron riêng: thêm hạ tầng không cần thiết với quy mô này |
| Sai email và sai mật khẩu cùng trả 401 với một thông báo, và vẫn verify dummy hash khi email không tồn tại | Không cho kẻ tấn công dò email nào có tài khoản, kể cả qua thời gian phản hồi | Trả "email không tồn tại": tiện cho người dùng nhưng lộ dữ liệu |
| PBKDF2-SHA256, 600.000 vòng, thư viện chuẩn | Khớp định dạng hash của seed (tương thích Django), không thêm dependency | bcrypt: phải đổi seed và thêm thư viện |
| HS256, cố định thuật toán khi verify | Một service duy nhất ký và kiểm tra token. Chặn tấn công `alg=none` hoặc đổi thuật toán | RS256: chỉ cần khi có nhiều service verify độc lập |
| Không có refresh token | Đề chỉ yêu cầu login/logout. Token 60 phút, hết hạn thì đăng nhập lại | Refresh token: thêm bảng, endpoint và cơ chế xoay vòng, để làm sau |

## 7. Giới hạn đã biết (làm sau)

- Chưa giới hạn số lần đăng nhập sai (rate limit). Khi triển khai thật nên đặt ở reverse proxy hoặc bằng bộ đếm theo IP + email.
- Chưa có API quản lý thành viên (tạo, đổi role, đổi mật khẩu) vì đề không yêu cầu. Role được đọc từ DB nên đổi role trực tiếp trong DB có hiệu lực ngay.

## 8. Hướng dẫn cho thành viên B, C

```python
from typing import Annotated
from fastapi import APIRouter, Depends
from app.auth import Database
from app.errors import AppError, error_responses, ok
from app.models import Envelope, Principal
from app.permissions import allow, require_permission

router = APIRouter(prefix='/api/orders', tags=['Orders'],
                   responses=error_responses({404: 'Order not found', 409: 'Invalid order status transition'}))

@router.get('/{id}', response_model=Envelope[OrderOut], dependencies=allow('orders:read'))
def get_order(id: int, connection: Database):
    row = connection.execute('SELECT ... WHERE id = %s', (id,)).fetchone()
    if row is None:
        raise AppError(404, 'Order not found')
    return ok(row)

@router.patch('/{id}/status', response_model=Envelope[OrderOut])
def change_status(id: int, body: StatusChange, connection: Database,
                  principal: Annotated[Principal, Depends(require_permission('orders:change-status'))]):
    # Người đổi lấy từ token (principal.id), KHÔNG lấy từ body.
    # set_config(..., true) = SET LOCAL, chỉ có hiệu lực trong transaction của request.
    connection.execute("SELECT set_config('app.member_id', %s, true), set_config('app.change_reason', %s, true)",
                       (str(principal.id), body.reason))
    ...
```

- Không tự viết exception handler riêng. Cần thông báo riêng cho một constraint mới thì thêm vào `CONSTRAINT_ERRORS` trong `app/errors.py`.
- Thêm quyền mới thì sửa `PERMISSIONS` và bảng ở mục 3, đồng thời cập nhật `tests/unit/test_permissions.py`.
- Thêm router thì `include_router` trong `app/main.py` và thêm tag vào `TAGS`.
