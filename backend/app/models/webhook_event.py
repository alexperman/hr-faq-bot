from datetime import datetime, timezone
from sqlalchemy import String, DateTime, Integer
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def _utcnow():
    return datetime.now(timezone.utc)


class WebhookEvent(Base):
    __tablename__ = "paypal_webhook_events"

    id: Mapped[int] = mapped_column(primary_key=True)

    paypal_event_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    event_type: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)

    verification_status: Mapped[str | None] = mapped_column(String(50), nullable=True)
    verified: Mapped[bool] = mapped_column(default=False)
    verification_detail: Mapped[str | None] = mapped_column(String(500), nullable=True)

    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    # Lightweight digest (avoid storing full payload)
    payload_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
