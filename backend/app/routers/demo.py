from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import FunnelEvent, User
from app.services.auth import get_current_user

router = APIRouter(prefix="/{tenant}/demo", tags=["demo"])


@router.post("/track")
async def track_demo_interaction(
    tenant: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Track demo page view / interaction as a funnel event."""

    # Tenant access is already enforced by get_current_user via JWT, but keep sanity.
    # We avoid tenant_slug lookup here to keep it lightweight.

    # Best-effort: if tenant mismatch, still allow logging (no secrets).
    try:
        db.add(
            FunnelEvent(
                event_type="demo_view",
                tenant_id=current_user.tenant_id,
                user_id=current_user.id,
                payload={"source": "product_page", "tenant_param": tenant},
            )
        )
        await db.commit()
    except Exception:
        await db.rollback()

    return {"status": "ok"}
