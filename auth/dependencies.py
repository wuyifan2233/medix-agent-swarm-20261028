import secrets
from fastapi import Depends, HTTPException, Request

from auth.schemas import CurrentUser
from auth.security import digest

WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def service(request: Request):
    return request.app.state.auth_service


def require_user(request: Request):
    """Checks authentication AND CSRF on every authenticated write route."""
    auth = service(request)
    user, record = auth.authenticate(request.cookies.get(auth.settings.cookie_name))
    if request.method in WRITE_METHODS:
        token = request.headers.get("x-csrf-token", "")
        if len(token) != 64 or not secrets.compare_digest(digest(token), record.csrf_token_hash):
            raise HTTPException(403, "安全校验失败，请刷新页面后重试。")
    request.state.auth_session_id = record.id
    return CurrentUser(user.id, user.username, user.display_name, user.role)


def require_admin(user: CurrentUser = Depends(require_user)):
    if user.role != "admin":
        raise HTTPException(403, "需要管理员权限。")
    return user
