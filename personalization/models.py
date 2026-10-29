from sqlalchemy import Float, ForeignKey, Integer, JSON
from sqlalchemy.orm import Mapped, mapped_column
from storage.database import Base


class HealthProfile(Base):
    __tablename__ = "health_profiles"
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    profile_data: Mapped[dict] = mapped_column(JSON, nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_at: Mapped[float] = mapped_column(Float, nullable=False)
    confirmed_at: Mapped[float | None] = mapped_column(Float, nullable=True)
