import time
import math
import uuid
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import Field
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError
from auth.models import User, AuthAttempt, SmsChallenge
from auth.schemas import StrictModel, CurrentUser, public_user, PhoneCredentials
from auth.dependencies import require_user, service
from auth.security import digest, new_token
from auth.security import passwords
from auth.password_policy import validate_new_password
from auth.router import client_ip, login_response
from auth.sms_provider import AliyunSms

router = APIRouter()
provider = AliyunSms()


class Phone(StrictModel):
    phone_number: str = Field(pattern=r"^1[3-9][0-9]{9}$")


class SmsVerify(StrictModel):
    challenge_id: str = Field(min_length=43, max_length=43)
    code: str = Field(pattern=r"^[0-9]{6}$")


class PhoneBind(SmsVerify):
    pass


class PhoneUnbind(SmsVerify):
    new_password: str = Field(min_length=8, max_length=20)


@router.post("/api/auth/phone/unbind/send")
def send_unbinding(request: Request, user: CurrentUser = Depends(require_user)):
    with service(request).sessions() as db:
        phone = db.get(User, user.id).phone_number
        if not phone:
            raise HTTPException(409, "账号未绑定手机号。")
    return begin(Phone(phone_number=phone), request, "unbind", user.id)


@router.post("/api/auth/phone/unbind")
def unbind_phone(data: PhoneUnbind, request: Request, user: CurrentUser = Depends(require_user)):
    try:
        validate_new_password(data.new_password)
    except ValueError:
        raise HTTPException(400, "密码须为 8–20 位，大小写字母、数字、符号至少包含三类。") from None
    hashed = passwords.hash(data.new_password)
    phone = consume(data, request, "unbind", user.id)
    auth = service(request)
    with auth.sessions() as db:
        result = db.execute(update(User).where(User.id == user.id, User.phone_number == phone)
            .values(phone_number=None, password_hash=hashed, has_password=True, updated_at=time.time()))
        if result.rowcount != 1:
            raise HTTPException(409, "手机号状态已变化，请刷新后重试。")
        db.commit()
        username = db.get(User, user.id).username
    auth.revoke(user.id)
    return {"username": username}


@router.get("/api/auth/sms/config")
def config():
    return {"enabled": provider.configured()}


def begin(data, request, purpose, user_id=None):
    if not provider.configured():
        raise HTTPException(503, "短信登录暂未配置，请使用账号密码登录。")
    auth = service(request)
    auth.limit("sms-send", client_ip(request), data.phone_number)
    now, token = time.time(), new_token()
    scheme = "medix-" + purpose + ("-" + digest(user_id)[:7] if user_id else "")
    with auth.sessions() as db:
        if db.bind.dialect.name == "sqlite":
            db.connection().exec_driver_sql("BEGIN IMMEDIATE")
        bucket = "sms-cooldown:" + digest(data.phone_number)
        if db.scalar(select(func.count()).select_from(AuthAttempt).where(
                AuthAttempt.bucket == bucket, AuthAttempt.created_at > now - 60)):
            last_sent = db.scalar(select(func.max(AuthAttempt.created_at)).where(AuthAttempt.bucket == bucket))
            remaining = max(1, math.ceil(last_sent + 60 - now))
            raise HTTPException(429, f"该手机号刚获取过验证码，请等待 {remaining} 秒后重试。", headers={"Retry-After":str(remaining)})
        db.add(AuthAttempt(bucket=bucket, created_at=now))
        db.execute(update(SmsChallenge).where(SmsChallenge.phone_number == data.phone_number,
            SmsChallenge.scheme == scheme).values(consumed=True))
        db.execute(delete(SmsChallenge).where(SmsChallenge.expires_at < now - 900))
        db.add(SmsChallenge(token_hash=digest(token), phone_number=data.phone_number, purpose=purpose,
            user_id=user_id, scheme=scheme, expires_at=now + 300, attempts=0, consumed=True))
        db.commit()
    provider.send(data.phone_number, scheme)
    with auth.sessions() as db:
        challenge = db.get(SmsChallenge, digest(token))
        challenge.expires_at = time.time() + 300
        challenge.consumed = False
        db.commit()
    return {"challenge_id":token, "retry_after":60, "expires_in":300}


def consume(data, request, purpose, user_id=None):
    auth = service(request)
    auth.limit("sms-verify", client_ip(request))
    with auth.sessions() as db:
        if db.bind.dialect.name == "sqlite":
            db.connection().exec_driver_sql("BEGIN IMMEDIATE")
        challenge = db.get(SmsChallenge, digest(data.challenge_id))
        if (not challenge or challenge.purpose != purpose or challenge.user_id != user_id
                or challenge.consumed or challenge.expires_at <= time.time() or challenge.attempts >= 5):
            raise HTTPException(400, "验证码已失效，请重新获取。")
        challenge.attempts += 1
        if not provider.verify(challenge.phone_number, challenge.scheme, data.code):
            db.commit()
            raise HTTPException(400, "验证码错误，请检查后重试。")
        challenge.consumed = True
        phone = challenge.phone_number
        db.commit()
        return phone


@router.post("/api/auth/sms/send")
def send_login(data: Phone, request: Request):
    return begin(data, request, "login")


@router.post("/api/auth/sms/login")
def sms_login(data: SmsVerify, request: Request, response: Response):
    phone = consume(data, request, "login")
    auth = service(request)
    with auth.sessions() as db:
        if db.bind.dialect.name == "sqlite":
            db.connection().exec_driver_sql("BEGIN IMMEDIATE")
        user = db.scalar(select(User).where(User.phone_number == phone))
        if not user:
            raise HTTPException(409, "手机号尚未注册，请先创建账号。")
        user_id = user.id
    return login_response(request, response, auth.phone_session(user_id))


@router.post("/api/auth/phone/send")
def send_binding(data: Phone, request: Request, user: CurrentUser = Depends(require_user)):
    with service(request).sessions() as db:
        if db.get(User, user.id).phone_number:
            raise HTTPException(409, "账号已绑定手机号，暂不支持更换。")
    return begin(data, request, "bind", user.id)


@router.post("/api/auth/phone/bind")
def bind_phone(data: PhoneBind, request: Request, user: CurrentUser = Depends(require_user)):
    auth = service(request)
    auth.limit("phone-bind", client_ip(request), user.id)
    with auth.sessions() as db:
        row = db.get(User, user.id)
        if row.phone_number:
            raise HTTPException(409, "账号已绑定手机号，暂不支持更换。")
    phone = consume(data, request, "bind", user.id)
    with auth.sessions() as db:
        # Conditional write also protects concurrent binding attempts.
        from sqlalchemy import update
        try:
            result = db.execute(update(User).where(User.id == user.id, User.phone_number.is_(None))
                .values(phone_number=phone, updated_at=time.time()))
            if result.rowcount != 1:
                raise HTTPException(409, "账号已绑定手机号，请刷新页面。")
            db.commit()
        except IntegrityError:
            db.rollback()
            raise HTTPException(409, "手机号无法绑定，可能已关联其他账号。") from None
    return {"phone_masked":phone[:3] + "****" + phone[-4:]}


@router.post("/api/auth/password/send")
def send_password_setup(request: Request, user: CurrentUser = Depends(require_user)):
    with service(request).sessions() as db:
        row = db.get(User, user.id)
        if row.has_password or not row.phone_number:
            raise HTTPException(409, "请使用修改密码功能。")
        phone = row.phone_number
    return begin(Phone(phone_number=phone), request, "setpwd", user.id)


@router.post("/api/auth/password/set")
def set_first_password(data: PhoneUnbind, request: Request, user: CurrentUser = Depends(require_user)):
    try:
        validate_new_password(data.new_password)
    except ValueError:
        raise HTTPException(400, "密码不符合要求。") from None
    hashed = passwords.hash(data.new_password)
    phone = consume(data, request, "setpwd", user.id)
    auth = service(request)
    with auth.sessions() as db:
        result = db.execute(update(User).where(User.id == user.id, User.has_password.is_(False),
            User.phone_number == phone).values(password_hash=hashed, has_password=True, updated_at=time.time()))
        if result.rowcount != 1:
            raise HTTPException(409, "账号状态已变化，请刷新。")
        db.commit()
    auth.revoke(user.id)
    return {"ok": True}


@router.post("/api/auth/password/reset/send")
def send_password_reset(data: Phone, request: Request):
    return begin(data, request, "reset")


@router.post("/api/auth/password/reset")
def reset_password(data: PhoneUnbind, request: Request):
    try:
        validate_new_password(data.new_password)
    except ValueError:
        raise HTTPException(400, "密码不符合要求。") from None
    hashed = passwords.hash(data.new_password)
    phone = consume(data, request, "reset")
    auth = service(request)
    with auth.sessions() as db:
        row = db.scalar(select(User).where(User.phone_number == phone))
        if not row or not row.is_active:
            raise HTTPException(400, "无法重设密码，请确认手机号已绑定可用账号。")
        row.password_hash = hashed
        row.has_password = True
        row.updated_at = time.time()
        from auth.models import AuthSession
        db.execute(update(AuthSession).where(AuthSession.user_id == row.id).values(revoked_at=time.time()))
        db.commit()
    return {"ok": True}


@router.post("/api/auth/phone/login")
def phone_password_login(data: PhoneCredentials, request: Request, response: Response):
    from auth.security import DUMMY_HASH
    auth = service(request)
    auth.limit("login", client_ip(request), data.phone_number)
    with auth.sessions() as db:
        row = db.scalar(select(User).where(User.phone_number == data.phone_number))
        valid = passwords.verify(data.password, row.password_hash if row else DUMMY_HASH)
        if not row or not valid or not row.is_active or not row.has_password:
            raise HTTPException(401, "手机号或密码错误；未设置密码请使用验证码登录。")
        user_id = row.id
    return login_response(request, response, auth.phone_session(user_id))


@router.post("/api/auth/phone/register/send")
def send_phone_registration(data: Phone, request: Request):
    if not service(request).settings.registration_enabled:
        raise HTTPException(403, "当前未开放注册。")
    return begin(data, request, "signup")


@router.post("/api/auth/phone/register")
def register_phone(data: PhoneUnbind, request: Request, response: Response):
    auth = service(request)
    if not auth.settings.registration_enabled:
        raise HTTPException(403, "当前未开放注册。")
    try:
        validate_new_password(data.new_password)
    except ValueError:
        raise HTTPException(400, "密码不符合要求。") from None
    hashed = passwords.hash(data.new_password)
    phone = consume(data, request, "signup")
    with auth.sessions() as db:
        if db.bind.dialect.name == "sqlite":
            db.connection().exec_driver_sql("BEGIN IMMEDIATE")
        if db.scalar(select(User.id).where(User.phone_number == phone)):
            raise HTTPException(409, "手机号已注册，请登录或找回密码。")
        name = "用户" + phone[-4:]
        if db.scalar(select(User.id).where(User.username == name)):
            name += "_" + uuid.uuid4().hex[:8]
        row = User(id=str(uuid.uuid4()), username=name, display_name="MediX " + name,
            phone_number=phone, password_hash=hashed, has_password=True, role="user")
        db.add(row)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            raise HTTPException(409, "手机号已注册，请登录。") from None
        user_id = row.id
    return login_response(request, response, auth.phone_session(user_id))


class AccountDeletion(SmsVerify):
    confirmation: str = Field(pattern="^注销账号$")


@router.post("/api/auth/account/delete/send")
def send_account_deletion(request: Request, user: CurrentUser = Depends(require_user)):
    with service(request).sessions() as db:
        row = db.get(User, user.id)
        if row.role == "admin":
            raise HTTPException(403, "管理员账号暂不支持自助注销。")
        if not row.phone_number:
            raise HTTPException(409, "请先绑定手机号，再验证注销。")
        phone = row.phone_number
    return begin(Phone(phone_number=phone), request, "delete", user.id)


@router.delete("/api/auth/account")
def delete_account(data: AccountDeletion, request: Request, response: Response,
                   user: CurrentUser = Depends(require_user)):
    auth = service(request)
    if user.role == "admin":
        raise HTTPException(403, "管理员账号暂不支持自助注销。")
    phone = consume(data, request, "delete", user.id)
    with auth.sessions() as db:
        row = db.get(User, user.id)
        if not row or row.phone_number != phone:
            raise HTTPException(409, "账号状态已变化，请刷新后重试。")
        db.execute(delete(SmsChallenge).where((SmsChallenge.user_id == user.id) | (SmsChallenge.phone_number == phone)))
        db.delete(row)
        db.commit()
    from auth.router import clear_cookie
    clear_cookie(response, auth.settings)
    # Runtime jobs have no persistent store; remove this user's private outputs.
    from web.app import jobs
    for key, job in list(jobs.items()):
        if job.get("owner_user_id") == user.id:
            jobs.pop(key, None)
    return {"ok": True}
