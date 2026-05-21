"""API Key model for MCP, CLI, Skills, and Agent authentication."""

from datetime import datetime, timezone
from sqlalchemy import String, Boolean, ForeignKey, DateTime, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def _utcnow():
    return datetime.now(timezone.utc)


class ApiKey(Base):
    __tablename__ = "api_keys"

    id: Mapped[int] = mapped_column(primary_key=True)
    # The key prefix shown to users (first 8 chars), full key is hashed
    key_prefix: Mapped[str] = mapped_column(String(12), index=True)
    key_hash: Mapped[str] = mapped_column(String(255), unique=True)
    name: Mapped[str] = mapped_column(String(255))  # Human-readable label
    # Who/what this key is for
    scope: Mapped[str] = mapped_column(String(50), default="agent")  # agent, mcp, cli, skill
    # Permissions
    permissions: Mapped[str] = mapped_column(Text, default="read")  # comma-separated: read,write,admin

    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Who created this key (must be a human user)
    created_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True)

    # Relationships
    created_by: Mapped["User"] = relationship(lazy="selectin")
    tenant: Mapped["Tenant"] = relationship(lazy="selectin")
