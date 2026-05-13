from datetime import datetime, timezone
from sqlalchemy import String, Integer, Text, Boolean, ForeignKey, DateTime
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def _utcnow():
    return datetime.now(timezone.utc)


class Escalation(Base):
    __tablename__ = "escalations"

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    question: Mapped[str] = mapped_column(Text)
    ai_partial_answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    admin_reply: Mapped[str | None] = mapped_column(Text, nullable=True)
    replied_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending, replied, read
    read_by_user: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    replied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    user: Mapped["User"] = relationship(foreign_keys=[user_id], lazy="selectin")
    replier: Mapped["User | None"] = relationship(foreign_keys=[replied_by], lazy="selectin")
