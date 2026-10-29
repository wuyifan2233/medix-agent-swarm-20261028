import time
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy import func, select, update

from auth.dependencies import require_admin, require_user, service
from auth.models import AuthSession, User
from auth.avatar import AvatarUpload, normalize_avatar
from auth.schemas import Credentials, CurrentUser, PasswordChange, Registration, StatusChange, public_user

router = APIRouter()


def clear_cookie(response, settings):
    response.delete_cookie(settings.cookie_name, path="/", secure=settings.production,
                           httponly=True, samesite="lax")


def client_ip(request):
    # Never trust arbitrary X-Forwarded-For. Uvicorn proxy trust must be configured at deployment.
    return request.client.host if request.client else "unknown"


@router.post("/api/auth/register", status_code=201)
def register(data: Registration, request: Request):
    auth = service(request)
    if not auth.settings.registration_enabled:
        raise HTTPException(403, "当前未开放注册，请联系管理员。")
    auth.limit("register", client_ip(request))
    return public_user(auth.register(data))


@router.post("/api/auth/login")
def login(data: Credentials, request: Request, response: Response):
    auth = service(request)
    auth.limit("login", client_ip(request), data.username)
    user, token, csrf = auth.login(data)
    # Logging in again in the same browser replaces and revokes its previous credential.
    previous = request.cookies.get(auth.settings.cookie_name)
    if previous:
        from auth.security import digest
        with auth.sessions() as db:
            db.execute(update(AuthSession).where(AuthSession.token_hash == digest(previous),
                       AuthSession.revoked_at.is_(None)).values(revoked_at=time.time()))
            db.commit()
    response.set_cookie(auth.settings.cookie_name, token, max_age=auth.settings.absolute_seconds,
                        path="/", secure=auth.settings.production, httponly=True, samesite="lax")
    return {"user": public_user(user), "csrf_token": csrf}


@router.get("/api/auth/me")
def me(request: Request, user: CurrentUser = Depends(require_user)):
    with service(request).sessions() as db:
        avatar = db.get(User, user.id).avatar_data
    return {"id": user.id, "username": user.username, "display_name": user.display_name, "role": user.role,
            "avatar_url": avatar}


@router.put("/api/auth/avatar")
def update_avatar(data: AvatarUpload, request: Request, user: CurrentUser = Depends(require_user)):
    try:
        avatar = normalize_avatar(data.data)
    except ValueError as error:
        raise HTTPException(400, str(error)) from error
    with service(request).sessions() as db:
        row = db.get(User, user.id)
        row.avatar_data = avatar
        row.updated_at = time.time()
        db.commit()
    return {"avatar_url": avatar}


@router.delete("/api/auth/avatar", status_code=204)
def reset_avatar(request: Request, user: CurrentUser = Depends(require_user)):
    with service(request).sessions() as db:
        row = db.get(User, user.id)
        row.avatar_data = None
        row.updated_at = time.time()
        db.commit()


@router.get("/api/auth/csrf")
def csrf(request: Request, user: CurrentUser = Depends(require_user)):
    auth = service(request)
    return {"csrf_token": auth.csrf_for_token(request.cookies[auth.settings.cookie_name])}


@router.post("/api/auth/logout", status_code=204)
def logout(request: Request, response: Response, user: CurrentUser = Depends(require_user)):
    auth = service(request)
    auth.revoke(user.id, request.state.auth_session_id)
    clear_cookie(response, auth.settings)


@router.post("/api/auth/logout-all", status_code=204)
def logout_all(request: Request, response: Response, user: CurrentUser = Depends(require_user)):
    auth = service(request)
    auth.revoke(user.id)
    clear_cookie(response, auth.settings)


@router.post("/api/auth/change-password", status_code=204)
def change_password(data: PasswordChange, request: Request, response: Response,
                    user: CurrentUser = Depends(require_user)):
    auth = service(request)
    auth.limit("password", client_ip(request), user.id)
    auth.change_password(user.id, data)
    clear_cookie(response, auth.settings)


@router.get("/api/admin/users")
def users(request: Request, offset: int = Query(0, ge=0), limit: int = Query(20, ge=1, le=100),
          user: CurrentUser = Depends(require_admin)):
    with service(request).sessions() as db:
        rows = db.scalars(select(User).order_by(User.created_at, User.id).offset(offset).limit(limit)).all()
        return {"items": [public_user(row) for row in rows], "total": db.scalar(select(func.count()).select_from(User))}


@router.patch("/api/admin/users/{user_id}/status")
def user_status(user_id: str, data: StatusChange, request: Request, user: CurrentUser = Depends(require_admin)):
    with service(request).sessions() as db:
        target = db.get(User, user_id)
        if not target:
            raise HTTPException(404, "用户不存在。")
        if target.role == "admin":
            raise HTTPException(403, "此接口仅管理普通账号。")
        target.is_active = data.is_active
        target.updated_at = time.time()
        if not data.is_active:
            db.execute(update(AuthSession).where(AuthSession.user_id == user_id,
                       AuthSession.revoked_at.is_(None)).values(revoked_at=time.time()))
        db.commit()
        return public_user(target)
