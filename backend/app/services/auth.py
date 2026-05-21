from datetime import datetime, timedelta, timezone
from jose import jwt, JWTError
from passlib.context import CryptContext
from fastapi import Depends, HTTPException, status, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import Literal

from app.config import get_settings
from app.database import get_db
from app.models import User
from app.services.structured_logger import log_event

settings = get_settings()
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
security = HTTPBearer()

# Session types for tracking how a request was made
SessionType = Literal["web", "cli", "mcp", "agent", "bot", "skill"]

# In-memory auth failure tracking (safe; no PII/tokens)
_auth_failure_events: list[dict] = []
_AUTH_FAILURE_EVENT_HISTORY = 200


def _record_auth_failure(reason: str) -> None:
    """Record an auth failure event (no secrets)."""
    _auth_failure_events.append({"reason": reason})
    if len(_auth_failure_events) > _AUTH_FAILURE_EVENT_HISTORY:
        del _auth_failure_events[: -_AUTH_FAILURE_EVENT_HISTORY]

    # Keep log records concise and non-sensitive.
    log_event(event="auth_failure", severity="medium", reason=reason)


def get_auth_failure_stats() -> dict:
    """Aggregate auth failures over short windows."""
    counts: dict[str, int] = {}
    for ev in _auth_failure_events[-_AUTH_FAILURE_EVENT_HISTORY:]:
        r = (ev.get("reason") or "unknown").strip()
        counts[r] = counts.get(r, 0) + 1
    return {
        "failures_total_recent": len(_auth_failure_events),
        "failures_by_reason_recent": counts,
        "recent_failures": _auth_failure_events[-10:],
    }


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def hash_api_key(key: str) -> str:
    """Hash an API key for storage (same bcrypt as passwords)."""
    return pwd_context.hash(key)


def verify_api_key(plain_key: str, hashed: str) -> bool:
    """Verify an API key against its hash."""
    return pwd_context.verify(plain_key, hashed)


def create_access_token(
    data: dict,
    expires_delta: timedelta | None = None,
    session_type: SessionType = "web",
) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    to_encode.update({"exp": expire, "session_type": session_type})
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def create_password_reset_token(user_id: int, email: str) -> str:
    """Create a short-lived token for password reset (15 min)."""
    data = {"user_id": user_id, "email": email, "purpose": "password_reset"}
    expire = datetime.now(timezone.utc) + timedelta(minutes=15)
    data["exp"] = expire
    return jwt.encode(data, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def verify_password_reset_token(token: str) -> dict | None:
    """Verify and decode a password reset token. Returns payload or None."""
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        if payload.get("purpose") != "password_reset":
            return None
        return payload
    except JWTError:
        return None


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_db),
) -> User:
    token = credentials.credentials
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        user_id: int = payload.get("user_id")
        if user_id is None:
            _record_auth_failure("missing_user_id")
            raise HTTPException(status_code=401, detail="Invalid token")
    except JWTError:
        _record_auth_failure("invalid_token")
        raise HTTPException(status_code=401, detail="Invalid token")

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        _record_auth_failure("user_not_found")
        raise HTTPException(status_code=401, detail="User not found")
    if not user.is_active:
        _record_auth_failure("user_inactive")
        raise HTTPException(status_code=401, detail="User not found")
    return user


async def get_session_info(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> dict:
    """Extract session metadata from the token (session_type, user_id, tenant_slug)."""
    token = credentials.credentials
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        return {
            "user_id": payload.get("user_id"),
            "tenant_slug": payload.get("tenant_slug"),
            "session_type": payload.get("session_type", "web"),
            "api_key_id": payload.get("api_key_id"),
        }
    except JWTError:
        return {"session_type": "unknown"}


async def authenticate_api_key(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> "tuple[User, dict]":
    """Authenticate via X-API-Key header. Returns (user, session_info).

    API keys are generated by human users and used by agents/CLI/MCP/skills.
    The key maps back to the creating user's tenant.
    """
    from app.models import ApiKey

    api_key_header = request.headers.get("x-api-key") or request.headers.get("X-API-Key")
    if not api_key_header:
        raise HTTPException(status_code=401, detail="Missing X-API-Key header")

    # Key prefix is first 8 chars for lookup
    prefix = api_key_header[:8] if len(api_key_header) >= 8 else api_key_header

    result = await db.execute(
        select(ApiKey).where(ApiKey.key_prefix == prefix, ApiKey.is_active == True)  # noqa: E712
    )
    candidates = result.scalars().all()

    matched_key = None
    for candidate in candidates:
        if verify_api_key(api_key_header, candidate.key_hash):
            matched_key = candidate
            break

    if matched_key is None:
        _record_auth_failure("invalid_api_key")
        raise HTTPException(status_code=401, detail="Invalid API key")

    # Check expiry
    if matched_key.expires_at and matched_key.expires_at < datetime.now(timezone.utc):
        _record_auth_failure("expired_api_key")
        raise HTTPException(status_code=401, detail="API key expired")

    # Update last_used_at
    matched_key.last_used_at = datetime.now(timezone.utc)
    await db.commit()

    # Load the creating user
    user_result = await db.execute(select(User).where(User.id == matched_key.created_by_user_id))
    user = user_result.scalar_one_or_none()
    if user is None or not user.is_active:
        raise HTTPException(status_code=401, detail="Key owner account inactive")

    session_info = {
        "user_id": user.id,
        "tenant_slug": matched_key.tenant.slug if matched_key.tenant else None,
        "session_type": matched_key.scope,  # agent, mcp, cli, skill
        "api_key_id": matched_key.id,
        "api_key_name": matched_key.name,
        "permissions": matched_key.permissions.split(",") if matched_key.permissions else ["read"],
    }

    return user, session_info
