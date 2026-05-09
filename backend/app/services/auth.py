from datetime import datetime, timedelta, timezone
from jose import jwt, JWTError
from passlib.context import CryptContext
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.config import get_settings
from app.database import get_db
from app.models import User

settings = get_settings()
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
security = HTTPBearer()

# In-memory auth failure tracking (safe; no PII/tokens)
_auth_failure_events: list[dict] = []
_AUTH_FAILURE_EVENT_HISTORY = 200


def _record_auth_failure(reason: str) -> None:
    """Record an auth failure event (no secrets)."""
    _auth_failure_events.append({"reason": reason})
    if len(_auth_failure_events) > _AUTH_FAILURE_EVENT_HISTORY:
        del _auth_failure_events[: -_AUTH_FAILURE_EVENT_HISTORY]


def get_auth_failure_stats() -> dict:
    """Aggregate auth failures over short windows."""
    # We only record reason; timestamps are not stored to keep it minimal.
    # Since hermes calls admin endpoints periodically, the counters reflect recent activity.
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


def create_access_token(data: dict, expires_delta: timedelta | None = None) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


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
