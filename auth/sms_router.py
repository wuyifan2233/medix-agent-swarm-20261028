import time
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import Field
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError
from auth.models import User, AuthAttempt, SmsChallenge
from auth.schemas import StrictModel, CurrentUser, public_user
from auth.dependencies import require_user, service
from auth.security import digest, new_token, passwords
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
    current_password: str = Field(min_length=1, max_length=128)


@router.get("/api/auth/sms/config")
def config():
    return {"enabled": provider.configured()}


def begin(data, request, purpose, user_id=None):
    if not provider.configured():
        raise HTTPException(503, "短信登录暂未配置，请使用账号密码登录。")
    auth = service(request)
    auth.limit("sms-send", client_ip(request), data.phone_number)
    now, token = time.time(), new_token()
    scheme = "medix-" + purpose + ("-" + digest(user_id)[:8] if user_id else "")
    with auth.sessions() as db:
        if db.bind.dialect.name == "sqlite":
            db.connection().exec_driver_sql("BEGIN IMMEDIATE")
        bucket = "sms-cooldown:" + digest(data.phone_number)
        if db.scalar(select(func.count()).select_from(AuthAttempt).where(
                AuthAttempt.bucket == bucket, AuthAttempt.created_at > now - 60)):
            raise HTTPException(429, "请等待 60 秒后再发送验证码。", headers={"Retry-After":"60"})
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
        user = db.scalar(select(User).where(User.phone_number == phone))
        if not user:
            raise HTTPException(409, "此手机号尚未绑定账号。请先用账号密码登录，在账号设置中绑定手机号。")
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
        if not passwords.verify(data.current_password, row.password_hash):
            raise HTTPException(400, "账号密码错误。")
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
