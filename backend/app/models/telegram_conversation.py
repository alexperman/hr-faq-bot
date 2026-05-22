from datetime import datetime, timezone
from sqlalchemy import String, DateTime, Index
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


def _utcnow():
    return datetime.now(timezone.utc)


class TelegramConversation(Base):
    """
    Stores conversation history per (bot_token, user_id) pair.
    Each Telegram bot has its own context that accumulates across messages.
    """
    __tablename__ = "telegram_conversations"

    id: Mapped[int] = mapped_column(primary_key=True)
    bot_token: Mapped[str] = mapped_column(String(100), index=True)
    user_id: Mapped[str] = mapped_column(String(64))  # Telegram chat_id as string
    history_json: Mapped[str] = mapped_column(String(65535))  # JSON-encoded message list
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)

    __table_args__ = (
        Index("ix_telegram_conv_bot_user", "bot_token", "user_id", unique=True),
    )