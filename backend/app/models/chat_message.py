from datetime import datetime, timezone
from sqlalchemy import String, Integer, Text, ForeignKey, DateTime
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def _utcnow():
    return datetime.now(timezone.utc)


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    role: Mapped[str] = mapped_column(String(10))  # "user" or "ai"
    content: Mapped[str] = mapped_column(Text)
    source_title: Mapped[str | None] = mapped_column(String(500), nullable=True)
    escalation_id: Mapped[int | None] = mapped_column(ForeignKey("escalations.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, index=True)
