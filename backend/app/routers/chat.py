from fastapi import APIRouter, Depends, HTTPException, status, Path
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel

from app.database import get_db
from app.models import User, Document, Tenant, Subscription
from app.services.auth import get_current_user
from app.services.groq import ask_groq
from app.services.rate_limit import check_rate_limit


router = APIRouter(prefix="/{tenant}/chat", tags=["chat"])


class AskRequest(BaseModel):
    question: str


class SourceDoc(BaseModel):
    title: str
    content: str


class AskResponse(BaseModel):
    answer: str
    sources: list[SourceDoc]


def simple_search(query: str, documents: list[Document], top_k: int = 5) -> list[Document]:
    """
    Simple keyword overlap scoring to find relevant documents.
    
    Scores each document by counting how many query keywords appear in its title and content.
    Returns the top_k most relevant documents.
    """
    query_words = set(query.lower().split())
    
    scored: list[tuple[int, Document]] = []
    for doc in documents:
        title_words = set(doc.title.lower().split())
        content_words = set(doc.content.lower().split())
        
        # Count keyword overlaps
        title_matches = len(query_words & title_words)
        content_matches = len(query_words & content_words)
        
        # Weighted score: title matches worth more than content matches
        score = title_matches * 2 + content_matches
        
        if score > 0:
            scored.append((score, doc))
    
    # Sort by score descending and return top_k
    scored.sort(key=lambda x: x[0], reverse=True)
    return [doc for _, doc in scored[:top_k]]


@router.post("/ask", response_model=AskResponse)
async def ask_question(
    request: AskRequest,
    tenant: str = Path(..., description="Tenant slug"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Ask an HR question and get an AI-generated answer based on the knowledge base.
    
    Requires JWT authentication and validates tenant access.
    Uses keyword search to find relevant documents, then calls the Groq AI.
    Rate limited to 20 requests/minute per user.
    """
    # Rate limit check
    check_rate_limit(current_user.id)
    # Validate tenant access
    tenant_result = await db.execute(select(Tenant).where(Tenant.slug == tenant))
    db_tenant = tenant_result.scalar_one_or_none()
    
    if db_tenant is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tenant not found",
        )
    
    if db_tenant.id != current_user.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied to this tenant",
        )

    sub_result = await db.execute(
        select(Subscription).where(Subscription.tenant_id == db_tenant.id)
    )
    subscription = sub_result.scalar_one_or_none()

    if subscription is None or subscription.status != "active":
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail="Subscription required (activate your plan to ask HR questions).",
        )

    # Fetch documents for this tenant's knowledge base
    docs_result = await db.execute(
        select(Document).where(Document.tenant_id == db_tenant.id)
    )
    all_docs = list(docs_result.scalars().all())
    
    # Handle empty knowledge base
    if not all_docs:
        return AskResponse(
            answer="The knowledge base is currently empty. Please add some HR documents first before asking questions.",
            sources=[],
        )
    
    # Search for relevant documents using keyword matching
    relevant_docs = simple_search(request.question, all_docs, top_k=5)
    
    if not relevant_docs:
        return AskResponse(
            answer="I couldn't find any relevant information in the knowledge base for your question. Please try rephrasing or contact HR directly for assistance.",
            sources=[],
        )
    
    # Prepare context from relevant documents
    context_docs = [
        f"Title: {doc.title}\nContent: {doc.content}" for doc in relevant_docs
    ]
    
    # Call Groq AI
    answer = await ask_groq(request.question, context_docs)
    
    # Build sources list
    sources = [
        SourceDoc(title=doc.title, content=doc.content[:500])
        for doc in relevant_docs
    ]
    
    return AskResponse(answer=answer, sources=sources)
