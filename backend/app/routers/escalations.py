from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, status, Path
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel

from app.database import get_db
from app.models import User, Tenant, Escalation, Document
from app.services.auth import get_current_user
from app.services.groq import ask_groq

router = APIRouter(prefix="/{tenant}/escalations", tags=["escalations"])


class EscalationOut(BaseModel):
    id: int
    question: str
    ai_partial_answer: str | None
    admin_reply: str | None
    status: str
    read_by_user: bool = False
    user_name: str
    user_email: str
    replier_name: str | None = None
    created_at: str
    replied_at: str | None

    model_config = {"from_attributes": True}


class ReplyRequest(BaseModel):
    reply: str


class ReplyWithKBRequest(BaseModel):
    """Admin can ask the KB for help composing a reply."""
    question: str


# ─── List escalations (admin/owner only) ─────────────────────────────────────

@router.get("/", response_model=list[EscalationOut])
async def list_escalations(
    tenant: str = Path(...),
    status_filter: str | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List all escalated questions for this tenant. Owners see all; members see their own."""
    tenant_result = await db.execute(select(Tenant).where(Tenant.slug == tenant))
    db_tenant = tenant_result.scalar_one_or_none()
    if db_tenant is None:
        raise HTTPException(status_code=404, detail="Tenant not found")
    if db_tenant.id != current_user.tenant_id:
        raise HTTPException(status_code=403, detail="Access denied")

    query = select(Escalation).where(Escalation.tenant_id == db_tenant.id)

    if not current_user.is_owner:
        # Non-owners only see their own escalations
        query = query.where(Escalation.user_id == current_user.id)

    if status_filter:
        query = query.where(Escalation.status == status_filter)

    query = query.order_by(Escalation.created_at.desc())
    result = await db.execute(query)
    escalations = result.scalars().all()

    return [
        EscalationOut(
            id=e.id,
            question=e.question,
            ai_partial_answer=e.ai_partial_answer,
            admin_reply=e.admin_reply,
            status=e.status,
            read_by_user=e.read_by_user,
            user_name=e.user.full_name if e.user else "Unknown",
            user_email=e.user.email if e.user else "",
            replier_name=e.replier.full_name if e.replier else None,
            created_at=e.created_at.isoformat(),
            replied_at=e.replied_at.isoformat() if e.replied_at else None,
        )
        for e in escalations
    ]


# ─── Get user's pending escalations (for notification badge) ─────────────────

@router.get("/my-replies", response_model=list[EscalationOut])
async def get_my_replies(
    tenant: str = Path(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get escalations that have been replied to for the current user (unread replies)."""
    tenant_result = await db.execute(select(Tenant).where(Tenant.slug == tenant))
    db_tenant = tenant_result.scalar_one_or_none()
    if db_tenant is None:
        raise HTTPException(status_code=404, detail="Tenant not found")
    if db_tenant.id != current_user.tenant_id:
        raise HTTPException(status_code=403, detail="Access denied")

    result = await db.execute(
        select(Escalation).where(
            Escalation.tenant_id == db_tenant.id,
            Escalation.user_id == current_user.id,
            Escalation.status == "replied",
        ).order_by(Escalation.replied_at.desc())
    )
    escalations = result.scalars().all()

    return [
        EscalationOut(
            id=e.id,
            question=e.question,
            ai_partial_answer=e.ai_partial_answer,
            admin_reply=e.admin_reply,
            status=e.status,
            read_by_user=e.read_by_user,
            user_name=e.user.full_name if e.user else "Unknown",
            user_email=e.user.email if e.user else "",
            replier_name=e.replier.full_name if e.replier else None,
            created_at=e.created_at.isoformat(),
            replied_at=e.replied_at.isoformat() if e.replied_at else None,
        )
        for e in escalations
    ]


# ─── Admin reply to an escalation ────────────────────────────────────────────

@router.post("/{escalation_id}/reply", response_model=EscalationOut)
async def reply_to_escalation(
    escalation_id: int,
    data: ReplyRequest,
    tenant: str = Path(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Admin replies to an escalated question. The user will see this reply."""
    if not current_user.is_owner:
        raise HTTPException(status_code=403, detail="Only admins can reply to escalations")

    tenant_result = await db.execute(select(Tenant).where(Tenant.slug == tenant))
    db_tenant = tenant_result.scalar_one_or_none()
    if db_tenant is None:
        raise HTTPException(status_code=404, detail="Tenant not found")
    if db_tenant.id != current_user.tenant_id:
        raise HTTPException(status_code=403, detail="Access denied")

    result = await db.execute(
        select(Escalation).where(Escalation.id == escalation_id, Escalation.tenant_id == db_tenant.id)
    )
    escalation = result.scalar_one_or_none()
    if escalation is None:
        raise HTTPException(status_code=404, detail="Escalation not found")

    escalation.admin_reply = data.reply
    escalation.replied_by = current_user.id
    escalation.replied_at = datetime.now(timezone.utc)
    escalation.status = "replied"
    await db.commit()
    await db.refresh(escalation)

    return EscalationOut(
        id=escalation.id,
        question=escalation.question,
        ai_partial_answer=escalation.ai_partial_answer,
        admin_reply=escalation.admin_reply,
        status=escalation.status,
        read_by_user=escalation.read_by_user,
        user_name=escalation.user.full_name if escalation.user else "Unknown",
        user_email=escalation.user.email if escalation.user else "",
        replier_name=escalation.replier.full_name if escalation.replier else None,
        created_at=escalation.created_at.isoformat(),
        replied_at=escalation.replied_at.isoformat() if escalation.replied_at else None,
    )


# ─── KB-assisted reply (admin asks KB for help) ──────────────────────────────

@router.post("/{escalation_id}/kb-assist")
async def kb_assisted_reply(
    escalation_id: int,
    data: ReplyWithKBRequest,
    tenant: str = Path(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Admin asks the KB for a suggested answer to help compose their reply."""
    if not current_user.is_owner:
        raise HTTPException(status_code=403, detail="Only admins can use KB assist")

    tenant_result = await db.execute(select(Tenant).where(Tenant.slug == tenant))
    db_tenant = tenant_result.scalar_one_or_none()
    if db_tenant is None:
        raise HTTPException(status_code=404, detail="Tenant not found")
    if db_tenant.id != current_user.tenant_id:
        raise HTTPException(status_code=403, detail="Access denied")

    # Fetch KB documents
    docs_result = await db.execute(select(Document).where(Document.tenant_id == db_tenant.id))
    all_docs = list(docs_result.scalars().all())

    if not all_docs:
        return {"suggestion": "No documents in the knowledge base to reference."}

    context_docs = [f"Title: {doc.title}\nContent: {doc.content}" for doc in all_docs[:5]]
    suggestion = await ask_groq(data.question, context_docs)

    return {"suggestion": suggestion}


# ─── Mark escalation as read (user acknowledges the reply) ───────────────────

@router.post("/{escalation_id}/read")
async def mark_as_read(
    escalation_id: int,
    tenant: str = Path(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Mark an escalation reply as read by the user."""
    tenant_result = await db.execute(select(Tenant).where(Tenant.slug == tenant))
    db_tenant = tenant_result.scalar_one_or_none()
    if db_tenant is None:
        raise HTTPException(status_code=404, detail="Tenant not found")
    if db_tenant.id != current_user.tenant_id:
        raise HTTPException(status_code=403, detail="Access denied")

    result = await db.execute(
        select(Escalation).where(
            Escalation.id == escalation_id,
            Escalation.tenant_id == db_tenant.id,
            Escalation.user_id == current_user.id,
        )
    )
    escalation = result.scalar_one_or_none()
    if escalation is None:
        raise HTTPException(status_code=404, detail="Not found")

    escalation.read_by_user = True
    await db.commit()
    return {"status": "read"}


# ─── Mark all replies as read ─────────────────────────────────────────────────

@router.post("/read-all")
async def mark_all_read(
    tenant: str = Path(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Mark all replied escalations as read for the current user."""
    tenant_result = await db.execute(select(Tenant).where(Tenant.slug == tenant))
    db_tenant = tenant_result.scalar_one_or_none()
    if db_tenant is None:
        raise HTTPException(status_code=404, detail="Tenant not found")
    if db_tenant.id != current_user.tenant_id:
        raise HTTPException(status_code=403, detail="Access denied")

    result = await db.execute(
        select(Escalation).where(
            Escalation.tenant_id == db_tenant.id,
            Escalation.user_id == current_user.id,
            Escalation.status == "replied",
            Escalation.read_by_user == False,
        )
    )
    unread = result.scalars().all()
    for e in unread:
        e.read_by_user = True
    await db.commit()
    return {"marked": len(unread)}
