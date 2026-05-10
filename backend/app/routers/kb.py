from fastapi import APIRouter, Depends, HTTPException, status, Path, UploadFile, File, Form
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel, field_validator
import httpx

from app.database import get_db
from app.models import Document, User, Tenant, Subscription
from app.services.auth import get_current_user
from app.services.kb_monitor import record_kb_failure
from app.config import get_settings

settings = get_settings()
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

    if not current_user.is_owner:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Owners only")

    sub_result = await db.execute(select(Subscription).where(Subscription.tenant_id == db_tenant.id))
    subscription = sub_result.scalar_one_or_none()

    if not settings.SKIP_SUBSCRIPTION_CHECK and (subscription is None or subscription.status != "active"):
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

    if not current_user.is_owner:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Owners only")

    sub_result = await db.execute(select(Subscription).where(Subscription.tenant_id == db_tenant.id))
    subscription = sub_result.scalar_one_or_none()

    if not settings.SKIP_SUBSCRIPTION_CHECK and (subscription is None or subscription.status != "active"):
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


def _extract_text_from_pdf(file_bytes: bytes) -> str:
    """Extract text from PDF bytes using PyMuPDF (fitz)."""
    try:
        import fitz
        doc = fitz.open(stream=file_bytes, filetype="pdf")
        text_parts = []
        for page in doc:
            text_parts.append(page.get_text())
        doc.close()
        return "\n".join(text_parts).strip()
    except Exception:
        try:
            import io
            from PyPDF2 import PdfReader
            reader = PdfReader(io.BytesIO(file_bytes))
            text_parts = []
            for page in reader.pages:
                t = page.extract_text()
                if t:
                    text_parts.append(t)
            return "\n".join(text_parts).strip()
        except Exception:
            return ""


@router.post("/upload", response_model=DocumentOut, status_code=status.HTTP_201_CREATED)
async def upload_document(
    tenant: str = Path(..., description="Tenant slug"),
    title: str = Form(...),
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Upload a file (PDF, TXT, MD) and extract its content into the knowledge base."""
    tenant_result = await db.execute(select(Tenant).where(Tenant.slug == tenant))
    db_tenant = tenant_result.scalar_one_or_none()
    if db_tenant is None:
        raise HTTPException(status_code=404, detail="Tenant not found")
    if db_tenant.id != current_user.tenant_id:
        raise HTTPException(status_code=403, detail="Access denied")

    file_bytes = await file.read()
    if len(file_bytes) > 10 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="File too large (max 10MB)")

    filename = file.filename or ""
    content_type = file.content_type or ""

    if filename.lower().endswith(".pdf") or "pdf" in content_type:
        content = _extract_text_from_pdf(file_bytes)
    elif filename.lower().endswith((".txt", ".md", ".markdown")):
        content = file_bytes.decode("utf-8", errors="replace")
    else:
        try:
            content = file_bytes.decode("utf-8")
        except UnicodeDecodeError:
            raise HTTPException(status_code=400, detail="Unsupported file format. Use PDF, TXT, or MD.")

    if not content or len(content.strip()) < 50:
        raise HTTPException(status_code=400, detail="Could not extract enough text (minimum 50 characters)")

    document = Document(title=title, content=content.strip(), source_url=None, char_count=len(content.strip()), tenant_id=db_tenant.id)
    db.add(document)
    await db.commit()
    await db.refresh(document)
    return DocumentOut(id=document.id, title=document.title, content=document.content, source_url=document.source_url, char_count=document.char_count, created_at=document.created_at.isoformat(), updated_at=document.updated_at.isoformat())


class ImportURLRequest(BaseModel):
    title: str
    url: str


@router.post("/import-url", response_model=DocumentOut, status_code=status.HTTP_201_CREATED)
async def import_from_url(
    data: ImportURLRequest,
    tenant: str = Path(..., description="Tenant slug"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Import a document by downloading from a URL."""
    tenant_result = await db.execute(select(Tenant).where(Tenant.slug == tenant))
    db_tenant = tenant_result.scalar_one_or_none()
    if db_tenant is None:
        raise HTTPException(status_code=404, detail="Tenant not found")
    if db_tenant.id != current_user.tenant_id:
        raise HTTPException(status_code=403, detail="Access denied")

    try:
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            resp = await client.get(data.url)
            resp.raise_for_status()
    except Exception:
        raise HTTPException(status_code=400, detail="Could not download from URL")

    file_bytes = resp.content
    if len(file_bytes) > 10 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="File too large (max 10MB)")

    ct = resp.headers.get("content-type", "")
    if "pdf" in ct or data.url.lower().endswith(".pdf"):
        content = _extract_text_from_pdf(file_bytes)
    else:
        content = file_bytes.decode("utf-8", errors="replace")
        if "<html" in content.lower()[:500]:
            import re
            content = re.sub(r'<script[^>]*>.*?</script>', '', content, flags=re.DOTALL | re.IGNORECASE)
            content = re.sub(r'<style[^>]*>.*?</style>', '', content, flags=re.DOTALL | re.IGNORECASE)
            content = re.sub(r'<[^>]+>', ' ', content)
            content = re.sub(r'\s+', ' ', content).strip()

    if not content or len(content.strip()) < 50:
        raise HTTPException(status_code=400, detail="Could not extract enough text from URL")

    document = Document(title=data.title, content=content.strip()[:500000], source_url=data.url, char_count=min(len(content.strip()), 500000), tenant_id=db_tenant.id)
    db.add(document)
    await db.commit()
    await db.refresh(document)
    return DocumentOut(id=document.id, title=document.title, content=document.content, source_url=document.source_url, char_count=document.char_count, created_at=document.created_at.isoformat(), updated_at=document.updated_at.isoformat())


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

    if not current_user.is_owner:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Owners only")

    sub_result = await db.execute(select(Subscription).where(Subscription.tenant_id == db_tenant.id))
    subscription = sub_result.scalar_one_or_none()

    if not settings.SKIP_SUBSCRIPTION_CHECK and (subscription is None or subscription.status != "active"):
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


@router.get("/{doc_id}", response_model=DocumentOut)
async def get_document(
    doc_id: int,
    tenant: str = Path(..., description="Tenant slug"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get a single document with full content for admin review."""
    tenant_result = await db.execute(select(Tenant).where(Tenant.slug == tenant))
    db_tenant = tenant_result.scalar_one_or_none()
    if db_tenant is None:
        raise HTTPException(status_code=404, detail="Tenant not found")
    if db_tenant.id != current_user.tenant_id:
        raise HTTPException(status_code=403, detail="Access denied")

    result = await db.execute(select(Document).where(Document.id == doc_id, Document.tenant_id == db_tenant.id))
    document = result.scalar_one_or_none()
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")

    return DocumentOut(
        id=document.id,
        title=document.title,
        content=document.content,
        source_url=document.source_url,
        char_count=document.char_count,
        created_at=document.created_at.isoformat(),
        updated_at=document.updated_at.isoformat(),
    )
