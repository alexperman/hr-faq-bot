from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from pydantic import BaseModel

from app.database import get_db
from app.models import Lead
from app.schemas.lead import LeadSubscribeRequest
from app.services.structured_logger import log_event


router = APIRouter(prefix="/leads", tags=["leads"])


@router.post("/subscribe")
async def subscribe_lead(
    req: LeadSubscribeRequest,
    db: AsyncSession = Depends(get_db),
):
    # Store lead (no tenant/user required).
    lead = Lead(email=req.email, source=req.source)

    try:
        db.add(lead)
        await db.commit()
        return {"status": "ok"}
    except IntegrityError:
        await db.rollback()
        # Treat duplicate as success (idempotent-ish for the funnel).
        log_event(event="lead_subscribe_duplicate", severity="info", email=str(req.email))
        return {"status": "already_registered"}
    except Exception as e:
        await db.rollback()
        log_event(event="lead_subscribe_failure", severity="high", error=str(e))
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Could not save lead")
