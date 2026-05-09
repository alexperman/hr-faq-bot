from fastapi import APIRouter, Depends, Header, HTTPException, status
from app.config import get_settings
from app.database import get_db
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models import WebhookEvent

settings = get_settings()
router = APIRouter(prefix="/admin", tags=["admin"])


def require_admin(authorization: str | None = Header(default=None)) -> None:
    if not settings.ADMIN_API_KEY:
        # If not configured, deny by default in production-like mode.
        # (Helps avoid accidental exposure.)
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Admin auth not configured")

    expected = f"Bearer {settings.ADMIN_API_KEY}"
    if authorization != expected:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid admin token")


@router.get("/health")
async def admin_health(_: None = Depends(require_admin)):
    return {"status": "ok"}


@router.get("/billing/webhook/latest")
async def latest_webhook_event(
    _: None = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return the latest PayPal webhook verification attempt."""
    result = await db.execute(
        select(WebhookEvent).order_by(WebhookEvent.received_at.desc()).limit(1)
    )
    ev = result.scalar_one_or_none()
    if not ev:
        return {"event": None}
    return {
        "event": {
            "paypal_event_id": ev.paypal_event_id,
            "event_type": ev.event_type,
            "verification_status": ev.verification_status,
            "verified": ev.verified,
            "verification_detail": ev.verification_detail,
            "received_at": ev.received_at.isoformat(),
        }
    }
