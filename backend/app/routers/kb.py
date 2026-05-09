from fastapi import APIRouter, Depends, HTTPException, status, Path
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel, field_validator

from app.database import get_db
from app.models import Document, User, Tenant, Subscription
from app.services.auth import get_current_user
from app.services.kb_monitor import record_kb_failure

router = APIRouter(prefix="/{tenant}/kb", tags=["kb"])


class DocumentCreate(BaseModel):
    title: str
    content: str
    source_url: str | None = None

    @field_validator("content")
    @classmethod
    def content_min_length(cls, v: str) -> str:
        if len(v) < 50:
            raise ValueError("Content must be at least 50 characters")
        return v


class DocumentOut(BaseModel):
    id: int
    title: str
    content: str
    source_url: str | None
    char_count: int
    created_at: str
    updated_at: str

    model_config = {"from_attributes": True}


@router.get("/", response_model=list[DocumentOut])
async def list_documents(
    tenant: str = Path(..., description="Tenant slug"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List all knowledge base documents for the current tenant (requires active subscription)."""

    tenant_result = await db.execute(select(Tenant).where(Tenant.slug == tenant))
    db_tenant = tenant_result.scalar_one_or_none()

    if db_tenant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found")

    if db_tenant.id != current_user.tenant_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied to this tenant")

    sub_result = await db.execute(select(Subscription).where(Subscription.tenant_id == db_tenant.id))
    subscription = sub_result.scalar_one_or_none()

    if subscription is None or subscription.status != "active":
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail="Subscription required (activate your plan to access HR documents).",
        )

    result = await db.execute(select(Document).where(Document.tenant_id == db_tenant.id))
    documents = result.scalars().all()
    return [
        DocumentOut(
            id=doc.id,
            title=doc.title,
            content=doc.content,
            source_url=doc.source_url,
            char_count=doc.char_count,
            created_at=doc.created_at.isoformat(),
            updated_at=doc.updated_at.isoformat(),
        )
        for doc in documents
    ]


@router.post("/", response_model=DocumentOut, status_code=status.HTTP_201_CREATED)
async def create_document(
    data: DocumentCreate,
    tenant: str = Path(..., description="Tenant slug"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a new knowledge base document (requires active subscription)."""

    tenant_result = await db.execute(select(Tenant).where(Tenant.slug == tenant))
    db_tenant = tenant_result.scalar_one_or_none()

    if db_tenant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found")

    if db_tenant.id != current_user.tenant_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied to this tenant")

    sub_result = await db.execute(select(Subscription).where(Subscription.tenant_id == db_tenant.id))
    subscription = sub_result.scalar_one_or_none()

    if subscription is None or subscription.status != "active":
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail="Subscription required (activate your plan to add HR documents).",
        )

    try:
        document = Document(
            title=data.title,
            content=data.content,
            source_url=data.source_url,
            char_count=len(data.content),
            tenant_id=db_tenant.id,
        )
        db.add(document)
        await db.commit()
        await db.refresh(document)
    except Exception as e:
        record_kb_failure(tenant_slug=tenant, reason=e.__class__.__name__)
        raise

    return DocumentOut(
        id=document.id,
        title=document.title,
        content=document.content,
        source_url=document.source_url,
        char_count=document.char_count,
        created_at=document.created_at.isoformat(),
        updated_at=document.updated_at.isoformat(),
    )


@router.delete("/{doc_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    doc_id: int,
    tenant: str = Path(..., description="Tenant slug"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete a knowledge base document by ID (requires active subscription)."""

    tenant_result = await db.execute(select(Tenant).where(Tenant.slug == tenant))
    db_tenant = tenant_result.scalar_one_or_none()

    if db_tenant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found")

    if db_tenant.id != current_user.tenant_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied to this tenant")

    sub_result = await db.execute(select(Subscription).where(Subscription.tenant_id == db_tenant.id))
    subscription = sub_result.scalar_one_or_none()

    if subscription is None or subscription.status != "active":
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail="Subscription required (activate your plan to manage HR documents).",
        )

    result = await db.execute(
        select(Document).where(
            Document.id == doc_id,
            Document.tenant_id == db_tenant.id,
        )
    )
    document = result.scalar_one_or_none()
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")
    await db.delete(document)
    await db.commit()
