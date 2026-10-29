import time
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError
from fastapi import HTTPException

from auth.models import AuthAttempt, AuthSession, User
from auth.security import DUMMY_HASH, digest, new_token, passwords


class AuthService:
    def __init__(self, sessions, settings):
        self.sessions = sessions
        self.settings = settings

    def limit(self, action, ip, username=None):
        now, window = time.time(), 900
        buckets = [(f"{action}:ip:{digest(ip)}", 30 if action == "login" else 10)]
        if username is not None:
            buckets.append((f"{action}:user:{digest(username)}", 10))
        with self.sessions() as db:
            # Serialize check + insert on SQLite so parallel requests cannot bypass the limit.
            if db.bind.dialect.name == "sqlite":
                db.connection().exec_driver_sql("BEGIN IMMEDIATE")
            db.execute(delete(AuthAttempt).where(AuthAttempt.created_at < now - window))
            for bucket, maximum in buckets:
                count = db.scalar(select(func.count()).select_from(AuthAttempt).where(
                    AuthAttempt.bucket == bucket, AuthAttempt.created_at >= now - window))
                if count >= maximum:
                    raise HTTPException(429, "尝试次数较多，请 15 分钟后重试。", headers={"Retry-After": "900"})
            db.add_all(AuthAttempt(bucket=bucket, created_at=now) for bucket, _ in buckets)
            db.commit()

    def register(self, data, role="user"):
        hashed = passwords.hash(data.password)
        with self.sessions() as db:
            user = User(username=data.username, display_name=data.display_name,
                        password_hash=hashed, role=role)
            db.add(user)
            try:
                db.commit()
            except IntegrityError:
                db.rollback()
                raise HTTPException(409, "无法使用该用户名，请更换后重试。")
            return user

    def login(self, data):
        with self.sessions() as db:
            if db.bind.dialect.name == "sqlite":
                db.connection().exec_driver_sql("BEGIN IMMEDIATE")
            user = db.scalar(select(User).where(User.username == data.username))
            valid, replacement = passwords.verify_and_update(data.password, user.password_hash if user else DUMMY_HASH)
            if not user or not valid or not user.is_active:
                raise HTTPException(401, "用户名或密码错误。")
            if replacement:
                user.password_hash = replacement
            now, token = time.time(), new_token()
            csrf = digest("csrf:" + token)
            db.execute(delete(AuthSession).where(AuthSession.expires_at < now))
            db.add(AuthSession(token_hash=digest(token), user_id=user.id, csrf_token_hash=digest(csrf),
                               created_at=now, last_seen_at=now, expires_at=now + self.settings.absolute_seconds))
            db.commit()
            return user, token, csrf

    def authenticate(self, token):
        if not token or len(token) != 43:
            raise HTTPException(401, "请先登录。")
        now = time.time()
        with self.sessions() as db:
            record = db.scalar(select(AuthSession).where(AuthSession.token_hash == digest(token)))
            user = db.get(User, record.user_id) if record else None
            if (not record or record.revoked_at is not None or record.expires_at <= now
                    or record.last_seen_at + self.settings.idle_seconds <= now or not user or not user.is_active):
                raise HTTPException(401, "登录已失效，请重新登录。")
            if now - record.last_seen_at >= 60:
                # Conditional update avoids a concurrent revoke being overwritten.
                db.execute(update(AuthSession).where(AuthSession.id == record.id,
                    AuthSession.revoked_at.is_(None)).values(last_seen_at=now))
                db.commit()
            return user, record

    def revoke(self, user_id, session_id=None):
        with self.sessions() as db:
            query = update(AuthSession).where(AuthSession.user_id == user_id, AuthSession.revoked_at.is_(None))
            if session_id:
                query = query.where(AuthSession.id == session_id)
            db.execute(query.values(revoked_at=time.time()))
            db.commit()

    def csrf_for_token(self, token):
        # Stable per login, so opening another tab does not invalidate existing tabs.
        # Domain separation and a high-entropy secret prevent recovery of the cookie.
        return digest("csrf:" + token)

    def change_password(self, user_id, data):
        with self.sessions() as db:
            if db.bind.dialect.name == "sqlite":
                db.connection().exec_driver_sql("BEGIN IMMEDIATE")
            user = db.get(User, user_id)
            if not passwords.verify(data.current_password, user.password_hash):
                raise HTTPException(400, "原密码错误。")
            user.password_hash = passwords.hash(data.new_password)
            user.updated_at = time.time()
            db.execute(update(AuthSession).where(AuthSession.user_id == user_id,
                       AuthSession.revoked_at.is_(None)).values(revoked_at=time.time()))
            db.commit()
