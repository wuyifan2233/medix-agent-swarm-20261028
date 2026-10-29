import time
import uuid

from sqlalchemy import Boolean, CheckConstraint, Float, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from storage.database import Base


class User(Base):
    __tablename__ = "users"
    __table_args__ = (CheckConstraint("role IN ('user', 'admin')", name="ck_users_role"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    username: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(60), nullable=False)
    avatar_data: Mapped[str | None] = mapped_column(Text, nullable=True)
    phone_number: Mapped[str | None] = mapped_column(String(11), unique=True, nullable=True)
    password_hash: Mapped[str] = mapped_column(String(512), nullable=False)
    role: Mapped[str] = mapped_column(String(16), default="user", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[float] = mapped_column(Float, default=time.time, nullable=False)
    updated_at: Mapped[float] = mapped_column(Float, default=time.time, nullable=False)


class AuthSession(Base):
    __tablename__ = "auth_sessions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    csrf_token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[float] = mapped_column(Float, nullable=False)
    last_seen_at: Mapped[float] = mapped_column(Float, nullable=False)
    expires_at: Mapped[float] = mapped_column(Float, nullable=False)
    revoked_at: Mapped[float | None] = mapped_column(Float, nullable=True)


class AuthAttempt(Base):
    """Shared, bounded-window rate limiting across local server processes."""
    __tablename__ = "auth_attempts"
    __table_args__ = (Index("ix_auth_attempt_bucket_time", "bucket", "created_at"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    bucket: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[float] = mapped_column(Float, nullable=False)


class SmsChallenge(Base):
    __tablename__ = "sms_challenges"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    phone_number: Mapped[str] = mapped_column(String(11), nullable=False)
    purpose: Mapped[str] = mapped_column(String(8), nullable=False)
    user_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    scheme: Mapped[str] = mapped_column(String(20), nullable=False)
    expires_at: Mapped[float] = mapped_column(Float, nullable=False)
    attempts: Mapped[int] = mapped_column(default=0, nullable=False)
    consumed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
