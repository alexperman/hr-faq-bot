from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel, field_validator

from app.database import get_db
from app.models import Document, User
from app.services.auth import get_current_user

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
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List all knowledge base documents for the current tenant."""
    result = await db.execute(
        select(Document).where(Document.tenant_id == current_user.tenant_id)
    )
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
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a new knowledge base document (content must be at least 50 characters)."""
    document = Document(
        title=data.title,
        content=data.content,
        source_url=data.source_url,
        char_count=len(data.content),
        tenant_id=current_user.tenant_id,
    )
    db.add(document)
    await db.commit()
    await db.refresh(document)
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
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete a knowledge base document by ID (scoped to tenant)."""
    result = await db.execute(
        select(Document).where(
            Document.id == doc_id,
            Document.tenant_id == current_user.tenant_id,
        )
    )
    document = result.scalar_one_or_none()
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")
    await db.delete(document)
    await db.commit()
