from sqlalchemy import Float, ForeignKey, Integer, JSON, String, Boolean
from sqlalchemy.orm import Mapped, mapped_column
from storage.database import Base


class HealthProfile(Base):
    __tablename__ = "health_profiles"
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    profile_data: Mapped[dict] = mapped_column(JSON, nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_at: Mapped[float] = mapped_column(Float, nullable=False)
    confirmed_at: Mapped[float | None] = mapped_column(Float, nullable=True)


class ProfileRevision(Base):
    __tablename__ = 'health_profile_revisions'
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'), primary_key=True)
    revision: Mapped[int] = mapped_column(Integer, primary_key=True)
    profile_data: Mapped[dict] = mapped_column(JSON, nullable=False)
    saved_at: Mapped[float] = mapped_column(Float, nullable=False)
    confirmed_at: Mapped[float | None] = mapped_column(Float, nullable=True)
    action: Mapped[str] = mapped_column(String(20), nullable=False)


class ProfileImport(Base):
    __tablename__ = 'health_profile_imports'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'), index=True)
    base_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    candidates: Mapped[list] = mapped_column(JSON, nullable=False)
    created_at: Mapped[float] = mapped_column(Float, nullable=False)
    expires_at: Mapped[float] = mapped_column(Float, nullable=False)
    consumed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class ReplyPreferences(Base):
    __tablename__ = 'reply_preferences'
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id',ondelete='CASCADE'),primary_key=True)
    data: Mapped[dict] = mapped_column(JSON,nullable=False)
    revision: Mapped[int] = mapped_column(Integer,nullable=False)
    updated_at: Mapped[float] = mapped_column(Float,nullable=False)
