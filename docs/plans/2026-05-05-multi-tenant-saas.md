# AlterZahen Multi-Tenant SaaS Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** Convert the single-tenant HR FAQ Bot into a multi-tenant SaaS product where companies sign up, manage their own knowledge base, and chat with an AI trained on their docs. Billed at $29/mo via PayPal.

**Architecture:**
- **FastAPI** backend replacing Flask
- **PostgreSQL** for all persistent data (tenants, users, KB entries, chat history)
- **Path-based tenant routing** (`/acme/api/...`, `/acme/kb`, `/acme/chat`)
- **PayPal Subscriptions** for billing (not Stripe)
- **JWT auth** per tenant
- Single deployment, unlimited tenants, no separate DB per tenant

**Tech Stack:**
- FastAPI + Uvicorn
- PostgreSQL (Render free tier)
- SQLAlchemy (async)
- Pydantic v2
- PayPal Python SDK
- JWT (python-jose)
- bcrypt (password hashing)
- Gunicorn + Uvicorn workers for production

---

## Project Structure

```
alterzahen/
├── backend/
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py              # FastAPI app entry point
│   │   ├── config.py            # Settings from env vars
│   │   ├── database.py          # Async SQLAlchemy setup
│   │   ├── models/
│   │   │   ├── __init__.py
│   │   │   ├── tenant.py        # Tenant model
│   │   │   ├── user.py          # User model (per tenant)
│   │   │   ├── document.py      # KB document model
│   │   │   └── subscription.py  # PayPal subscription tracking
│   │   ├── schemas/
│   │   │   ├── __init__.py
│   │   │   ├── tenant.py
│   │   │   ├── user.py
│   │   │   ├── document.py
│   │   │   └── chat.py
│   │   ├── routers/
│   │   │   ├── __init__.py
│   │   │   ├── auth.py          # /auth/* — login, register, token refresh
│   │   │   ├── tenant.py        # /tenants/* — signup, onboarding
│   │   │   ├── kb.py            # /{tenant}/kb/* — knowledge base CRUD
│   │   │   ├── chat.py          # /{tenant}/chat/* — ask question
│   │   │   └── billing.py       # /{tenant}/billing/* — PayPal webhooks + portal
│   │   ├── services/
│   │   │   ├── __init__.py
│   │   │   ├── paypal.py        # PayPal subscription create/cancel/check
│   │   │   └── groq.py         # Groq AI calls
│   │   └── templates/
│   │       ├── login.html
│   │       ├── dashboard.html   # KB management UI
│   │       └── chat.html        # Chat widget page
│   ├── tests/
│   │   ├── conftest.py
│   │   ├── test_auth.py
│   │   ├── test_kb.py
│   │   ├── test_chat.py
│   │   └── test_billing.py
│   ├── requirements.txt
│   └── Procfile
├── frontend/                     # Marketing landing page (Vercel/Netlify)
│   ├── index.html
│   ├── pricing.html
│   ├── features.html
│   └── signup.html              # Redirects to /{tenant}/onboarding
├── docs/
│   └── plans/
└── README.md
```

---

## Phase 1: Foundation

### Task 1: Create FastAPI project skeleton

**Objective:** Set up the new FastAPI project structure with dependencies

**Files:**
- Create: `backend/requirements.txt`
- Create: `backend/app/__init__.py`
- Create: `backend/app/config.py`
- Create: `backend/app/database.py`
- Create: `backend/app/main.py`

**Step 1: Write `backend/requirements.txt`**

```
fastapi>=0.115.0
uvicorn[standard]>=0.32.0
sqlalchemy[asyncio]>=2.0.0
asyncpg>=0.30.0
pydantic>=2.10.0
pydantic-settings>=2.6.0
python-jose[cryptography]>=3.3.0
passlib[bcrypt]>=1.7.4
python-multipart>=0.0.20
paypalrestsdk>=1.14.0
httpx>=0.28.0
pytest>=8.0.0
pytest-asyncio>=0.25.0
gunicorn>=21.0.0
```

**Step 2: Run install**

```bash
cd /root/hr-faq-bot/backend && .venv/bin/pip install -r requirements.txt
```

**Step 3: Write `backend/app/config.py`**

```python
from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # Database
    DATABASE_URL: str = "postgresql+asyncpg://user:pass@localhost:5432/alterzahen"

    # JWT
    SECRET_KEY: str = "change-me-in-production"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24  # 24 hours

    # Groq AI
    GROQ_API_KEY: str = ""

    # PayPal
    PAYPAL_CLIENT_ID: str = ""
    PAYPAL_CLIENT_SECRET: str = ""
    PAYPAL_MODE: str = "sandbox"  # or "live"

    # App
    APP_URL: str = "http://localhost:8000"
    PRICE_ID: str = "P-XXXXXXXXXXXXXXXX"  # PayPal product/plan ID

    class Config:
        env_file = ".env"


@lru_cache
def get_settings() -> Settings:
    return Settings()
```

**Step 4: Write `backend/app/database.py`**

```python
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase

from app.config import get_settings

settings = get_settings()

engine = create_async_engine(settings.DATABASE_URL, echo=False)

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()
```

**Step 5: Write `backend/app/main.py`**

```python
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.database import engine, Base

settings = get_settings()

app = FastAPI(title="AlterZahen API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def startup():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


@app.get("/health")
async def health():
    return {"status": "ok"}
```

**Step 6: Verify**

```bash
cd /root/hr-faq-bot/backend && .venv/bin/python -c "from app.main import app; print('FastAPI app loads OK')"
```

Expected: `FastAPI app loads OK`

---

### Task 2: Create database models

**Objective:** Define Tenant, User, Document, Subscription models

**Files:**
- Create: `backend/app/models/__init__.py`
- Create: `backend/app/models/tenant.py`
- Create: `backend/app/models/user.py`
- Create: `backend/app/models/document.py`
- Create: `backend/app/models/subscription.py`

**Step 1: Write `backend/app/models/tenant.py`**

```python
from sqlalchemy import String, Boolean, DateTime
from sqlalchemy.orm import Mapped, mapped_column, relationship
from datetime import datetime

from app.database import Base


class Tenant(Base):
    __tablename__ = "tenants"

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(63), unique=True, index=True)  # e.g. "acme-corp"
    name: Mapped[str] = mapped_column(String(255))  # Company name
    logo_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    primary_color: Mapped[str] = mapped_column(String(7), default="#3B82F6")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # Relations
    users: Mapped[list["User"]] = relationship(back_populates="tenant", lazy="selectin")
    documents: Mapped[list["Document"]] = relationship(back_populates="tenant", lazy="selectin")
    subscription: Mapped["Subscription | None"] = relationship(back_populates="tenant", uselist=False)
```

**Step 2: Write `backend/app/models/user.py`**

```python
from sqlalchemy import String, Boolean, ForeignKey, DateTime
from sqlalchemy.orm import Mapped, mapped_column, relationship
from datetime import datetime

from app.database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    full_name: Mapped[str] = mapped_column(String(255))
    is_owner: Mapped[bool] = mapped_column(Boolean, default=False)  # First user = owner
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"))
    tenant: Mapped["Tenant"] = relationship(back_populates="users")
```

**Step 3: Write `backend/app/models/document.py`**

```python
from sqlalchemy import String, Text, Integer, ForeignKey, DateTime
from sqlalchemy.orm import Mapped, mapped_column, relationship
from datetime import datetime

from app.database import Base


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(500))
    content: Mapped[str] = mapped_column(Text)  # Min 50 chars enforced at service layer
    source_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    char_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"))
    tenant: Mapped["Tenant"] = relationship(back_populates="documents")
```

**Step 4: Write `backend/app/models/subscription.py`**

```python
from sqlalchemy import String, Boolean, ForeignKey, DateTime
from sqlalchemy.orm import Mapped, mapped_column, relationship
from datetime import datetime

from app.database import Base


class Subscription(Base):
    __tablename__ = "subscriptions"

    id: Mapped[int] = mapped_column(primary_key=True)
    paypal_subscription_id: Mapped[str | None] = mapped_column(String(255), unique=True, nullable=True)
    paypal_plan_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(50), default="pending")  # pending, active, cancelled, expired
    current_period_end: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), unique=True)
    tenant: Mapped["Tenant"] = relationship(back_populates="subscription")
```

**Step 5: Write `backend/app/models/__init__.py`**

```python
from app.models.tenant import Tenant
from app.models.user import User
from app.models.document import Document
from app.models.subscription import Subscription

__all__ = ["Tenant", "User", "Document", "Subscription"]
```

**Step 6: Verify models load**

```bash
cd /root/hr-faq-bot/backend && .venv/bin/python -c "from app.models import Tenant, User, Document, Subscription; print('Models load OK')"
```

---

## Phase 2: Authentication

### Task 3: Create Pydantic schemas + auth utilities

**Files:**
- Create: `backend/app/schemas/__init__.py`
- Create: `backend/app/schemas/user.py`
- Create: `backend/app/schemas/document.py`
- Create: `backend/app/schemas/chat.py`
- Create: `backend/app/services/auth.py`

**Step 1: Write `backend/app/schemas/user.py`**

```python
from pydantic import BaseModel, EmailStr


class UserCreate(BaseModel):
    email: EmailStr
    password: str  # Min 8 chars
    full_name: str
    company_name: str  # Used to create tenant slug


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class TokenData(BaseModel):
    user_id: int
    tenant_slug: str


class UserOut(BaseModel):
    id: int
    email: str
    full_name: str
    is_owner: bool
    tenant_slug: str

    class Config:
        from_attributes = True
```

**Step 2: Write `backend/app/services/auth.py`**

```python
from datetime import datetime, timedelta
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


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def create_access_token(data: dict, expires_delta: timedelta | None = None) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES))
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
            raise HTTPException(status_code=401, detail="Invalid token")
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None or not user.is_active:
        raise HTTPException(status_code=401, detail="User not found")
    return user
```

**Step 3: Write `backend/app/schemas/__init__.py`**

```python
from app.schemas.user import UserCreate, UserLogin, Token, TokenData, UserOut
```

---

### Task 4: Create auth router

**Files:**
- Create: `backend/app/routers/auth.py`

**Step 1: Write `backend/app/routers/auth.py`**

```python
import re
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.database import get_db
from app.models import User, Tenant, Subscription
from app.schemas import UserCreate, UserLogin, Token, UserOut
from app.services.auth import hash_password, verify_password, create_access_token, get_current_user

router = APIRouter(prefix="/auth", tags=["auth"])


def slugify(name: str) -> str:
    """Convert company name to URL-safe slug."""
    slug = re.sub(r'[^a-z0-9]+', '-', name.lower()).strip('-')
    # Ensure uniqueness by appending random suffix if needed (checked at DB level)
    return slug


@router.post("/register", response_model=Token)
async def register(data: UserCreate, db: AsyncSession = Depends(get_db)):
    # Check password strength
    if len(data.password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters")

    # Create tenant
    slug = slugify(data.company_name)
    tenant = Tenant(name=data.company_name, slug=slug)
    db.add(tenant)
    await db.flush()  # Get tenant.id

    # Create user (owner)
    password_hash = hash_password(data.password)
    user = User(
        email=data.email,
        password_hash=password_hash,
        full_name=data.full_name,
        tenant_id=tenant.id,
        is_owner=True,
    )
    db.add(user)

    # Create pending subscription record
    subscription = Subscription(tenant_id=tenant.id, status="pending")
    db.add(subscription)

    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="Email already registered")

    # Generate token
    token = create_access_token(data={"user_id": user.id, "tenant_slug": slug})
    return Token(access_token=token)


@router.post("/login", response_model=Token)
async def login(data: UserLogin, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.email == data.email))
    user = result.scalar_one_or_none()

    if user is None or not verify_password(data.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account disabled")

    # Get tenant slug
    tenant_result = await db.execute(select(Tenant).where(Tenant.id == user.tenant_id))
    tenant = tenant_result.scalar_one()

    token = create_access_token(data={"user_id": user.id, "tenant_slug": tenant.slug})
    return Token(access_token=token)


@router.get("/me", response_model=UserOut)
async def get_me(current_user: User = Depends(get_current_user)):
    return current_user
```

---

## Phase 3: Knowledge Base

### Task 5: Create KB router

**Files:**
- Create: `backend/app/routers/kb.py`

**Step 1: Write `backend/app/routers/kb.py`**

```python
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.models import Document, User, Tenant
from app.services.auth import get_current_user
from pydantic import BaseModel

router = APIRouter(prefix="/{tenant}/kb", tags=["knowledge base"])


def get_tenant_or_403(slug: str, db: AsyncSession) -> Tenant:
    """Dependency to validate tenant exists and is active."""
    # This will be used as a dependency — implemented inline


class DocumentCreate(BaseModel):
    title: str
    content: str
    source_url: str | None = None


class DocumentOut(BaseModel):
    id: int
    title: str
    content: str
    source_url: str | None
    char_count: int
    created_at: str
    updated_at: str

    class Config:
        from_attributes = True


class DocumentList(BaseModel):
    documents: list[DocumentOut]
    total: int


@router.get("/", response_model=DocumentList)
async def list_documents(
    tenant: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Validate tenant access
    result = await db.execute(
        select(Tenant).where(Tenant.slug == tenant, Tenant.id == current_user.tenant_id)
    )
    if (t := result.scalar_one_or_none()) is None or not t.is_active:
        raise HTTPException(status_code=404, detail="Workspace not found")

    doc_result = await db.execute(
        select(Document)
        .where(Document.tenant_id == current_user.tenant_id)
        .order_by(Document.created_at.desc())
    )
    docs = doc_result.scalars().all()
    return DocumentList(documents=docs, total=len(docs))


@router.post("/", response_model=DocumentOut)
async def add_document(
    tenant: str,
    data: DocumentCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if len(data.content) < 50:
        raise HTTPException(status_code=400, detail="Document must be at least 50 characters")

    # Validate tenant access
    result = await db.execute(
        select(Tenant).where(Tenant.slug == tenant, Tenant.id == current_user.tenant_id)
    )
    if result.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="Workspace not found")

    doc = Document(
        title=data.title,
        content=data.content,
        source_url=data.source_url,
        char_count=len(data.content),
        tenant_id=current_user.tenant_id,
    )
    db.add(doc)
    await db.commit()
    await db.refresh(doc)
    return doc


@router.delete("/{doc_id}")
async def delete_document(
    tenant: str,
    doc_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Document).where(
            Document.id == doc_id,
            Document.tenant_id == current_user.tenant_id,
        )
    )
    doc = result.scalar_one_or_none()
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found")

    await db.delete(doc)
    await db.commit()
    return {"ok": True}
```

---

## Phase 4: Chat

### Task 6: Create chat router with Groq AI

**Files:**
- Create: `backend/app/routers/chat.py`
- Create: `backend/app/services/groq.py`

**Step 1: Write `backend/app/services/groq.py`**

```python
import httpx
from app.config import get_settings

settings = get_settings()

GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"


async def ask_groq(question: str, context_docs: list[dict]) -> str:
    """
    Call Groq AI with KB context to answer a question.
    context_docs: list of {"title": str, "content": str}
    """
    if not settings.GROQ_API_KEY:
        return "AI not configured. Set GROQ_API_KEY."

    # Build context string
    context = "\n\n".join(
        f"[Source: {d['title']}]\n{d['content']}" for d in context_docs
    )

    system_prompt = f"""You are a helpful HR assistant. Answer questions based ONLY on the provided context.
If the answer is not in the context, say "I don't have that information in your knowledge base."
Keep answers concise and helpful.

Context:
{context}
"""

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            GROQ_API_URL,
            headers={
                "Authorization": f"Bearer {settings.GROQ_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": "llama-3.3-70b-versatile",
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": question},
                ],
                "temperature": 0.3,
            },
        )
        response.raise_for_status()
        data = response.json()
        return data["choices"][0]["message"]["content"]
```

**Step 2: Write `backend/app/routers/chat.py`**

```python
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_
from pydantic import BaseModel

from app.database import get_db
from app.models import Document, User, Tenant
from app.services.auth import get_current_user
from app.services.groq import ask_groq

router = APIRouter(prefix="/{tenant}/chat", tags=["chat"])


class AskRequest(BaseModel):
    question: str


class AskResponse(BaseModel):
    answer: str
    sources: list[dict]  # [{"title": str, "content": str}]


def simple_search(query: str, documents: list, top_k: int = 5) -> list:
    """
    Simple keyword search. Returns top_k documents by keyword overlap.
    """
    query_words = set(query.lower().split())
    scored = []
    for doc in documents:
        content_words = set(doc.content.lower().split())
        overlap = len(query_words & content_words)
        if overlap > 0:
            scored.append((overlap, doc))
    scored.sort(reverse=True)
    return [doc for _, doc in scored[:top_k]]


@router.post("/ask", response_model=AskResponse)
async def ask_question(
    tenant: str,
    data: AskRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not data.question.strip():
        raise HTTPException(status_code=400, detail="Question cannot be empty")

    # Validate tenant
    result = await db.execute(
        select(Tenant).where(Tenant.slug == tenant, Tenant.id == current_user.tenant_id)
    )
    if result.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="Workspace not found")

    # Get all documents for tenant
    doc_result = await db.execute(
        select(Document).where(Document.tenant_id == current_user.tenant_id)
    )
    documents = list(doc_result.scalars().all())

    if not documents:
        return AskResponse(
            answer="Your knowledge base is empty. Add some documents first.",
            sources=[],
        )

    # Search for relevant docs
    relevant_docs = simple_search(data.question, documents, top_k=5)
    context = [{"title": d.title, "content": d.content} for d in relevant_docs]

    answer = await ask_groq(data.question, context)

    return AskResponse(answer=answer, sources=context)
```

---

## Phase 5: Billing with PayPal

### Task 7: Create billing router

**Files:**
- Create: `backend/app/routers/billing.py`
- Create: `backend/app/services/paypal.py`

**Step 1: Write `backend/app/services/paypal.py`**

```python
import httpx
from app.config import get_settings

settings = get_settings()

PAYPAL_API = "https://api-m.sandbox.paypal.com" if settings.PAYPAL_MODE == "sandbox" else "https://api-m.paypal.com"


async def get_paypal_access_token() -> str:
    """Get OAuth2 access token from PayPal."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            f"{PAYPAL_API}/v1/oauth2/token",
            headers={
                "Accept": "application/json",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data={"grant_type": "client_credentials"},
            auth=(settings.PAYPAL_CLIENT_ID, settings.PAYPAL_CLIENT_SECRET),
        )
        response.raise_for_status()
        return response.json()["access_token"]


async def create_subscription(name: str, email: str, plan_id: str) -> dict:
    """Create a PayPal subscription and return the approval URL."""
    token = await get_paypal_access_token()
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            f"{PAYPAL_API}/v1/billing/subscriptions",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            json={
                "plan_id": plan_id,
                "subscriber": {
                    "name": {"given_name": name},
                    "email_address": email,
                },
                "application_context": {
                    "brand_name": "AlterZahen",
                    "return_url": f"{settings.APP_URL}/billing/success",
                    "cancel_url": f"{settings.APP_URL}/billing/cancel",
                },
            },
        )
        response.raise_for_status()
        data = response.json()
        # Find approval URL
        approval_url = next(
            link["href"] for link in data["links"] if link["rel"] == "approve"
        )
        return {"subscription_id": data["id"], "approval_url": approval_url}


async def get_subscription_status(subscription_id: str) -> str:
    """Check subscription status from PayPal."""
    token = await get_paypal_access_token()
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(
            f"{PAYPAL_API}/v1/billing/subscriptions/{subscription_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        response.raise_for_status()
        return response.json()["status"]


async def cancel_subscription(subscription_id: str) -> bool:
    """Cancel a PayPal subscription."""
    token = await get_paypal_access_token()
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            f"{PAYPAL_API}/v1/billing/subscriptions/{subscription_id}/cancel",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            json={"reason": "Customer requested cancellation"},
        )
        return response.status_code in (204, 200)
```

**Step 2: Write `backend/app/routers/billing.py`**

```python
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.models import User, Tenant, Subscription
from app.services.auth import get_current_user
from app.services.paypal import create_subscription, get_subscription_status, cancel_subscription
from pydantic import BaseModel

router = APIRouter(prefix="/{tenant}/billing", tags=["billing"])


class SubscribeResponse(BaseModel):
    approval_url: str


class WebhookEvent(BaseModel):
    event_type: str
    resource: dict


@router.get("/status")
async def get_billing_status(
    tenant: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get current subscription status for the tenant."""
    result = await db.execute(
        select(Subscription).where(Subscription.tenant_id == current_user.tenant_id)
    )
    sub = result.scalar_one_or_none()
    if sub is None:
        return {"status": "no_subscription"}
    return {
        "status": sub.status,
        "current_period_end": sub.current_period_end.isoformat() if sub.current_period_end else None,
        "subscription_id": sub.paypal_subscription_id,
    }


@router.post("/subscribe", response_model=SubscribeResponse)
async def start_subscription(
    tenant: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create PayPal subscription for the tenant."""
    if current_user.tenant_slug != tenant:
        raise HTTPException(status_code=403, detail="Access denied")

    # Get tenant and subscription
    result = await db.execute(
        select(Subscription).where(Subscription.tenant_id == current_user.tenant_id)
    )
    sub = result.scalar_one_or_none()
    if sub is None:
        raise HTTPException(status_code=404, detail="No subscription record found")

    if sub.status == "active":
        raise HTTPException(status_code=400, detail="Subscription already active")

    # Get plan ID from settings
    from app.config import get_settings
    settings = get_settings()

    result = await db.execute(select(Tenant).where(Tenant.id == current_user.tenant_id))
    tenant_obj = result.scalar_one()

    try:
        paypal_data = await create_subscription(
            name=current_user.full_name,
            email=current_user.email,
            plan_id=settings.PRICE_ID,
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"PayPal error: {str(e)}")

    # Store PayPal subscription ID
    sub.paypal_subscription_id = paypal_data["subscription_id"]
    await db.commit()

    return SubscribeResponse(approval_url=paypal_data["approval_url"])


@router.post("/webhook")
async def paypal_webhook(request: Request, db: AsyncSession = Depends(get_db)):
    """
    Receive PayPal webhook events.
    In production: verify webhook signature.
    """
    body = await request.json()
    event_type = body.get("event_type")
    resource = body.get("resource", {})

    if event_type == "BILLING.SUBSCRIPTION.ACTIVATED":
        sub_id = resource.get("id")
        result = await db.execute(
            select(Subscription).where(Subscription.paypal_subscription_id == sub_id)
        )
        sub = result.scalar_one_or_none()
        if sub:
            sub.status = "active"
            # Calculate period end
            from datetime import datetime, timedelta
            sub.current_period_end = datetime.utcnow() + timedelta(days=30)
            await db.commit()

    elif event_type == "BILLING.SUBSCRIPTION.CANCELLED":
        sub_id = resource.get("id")
        result = await db.execute(
            select(Subscription).where(Subscription.paypal_subscription_id == sub_id)
        )
        sub = result.scalar_one_or_none()
        if sub:
            sub.status = "cancelled"
            await db.commit()

    elif event_type == "BILLING.SUBSCRIPTION.EXPIRED":
        sub_id = resource.get("id")
        result = await db.execute(
            select(Subscription).where(Subscription.paypal_subscription_id == sub_id)
        )
        sub = result.scalar_one_or_none()
        if sub:
            sub.status = "expired"
            # Disable tenant
            tenant_result = await db.execute(
                select(Tenant).where(Tenant.id == sub.tenant_id)
            )
            tenant = tenant_result.scalar_one()
            tenant.is_active = False
            await db.commit()

    return {"ok": True}


@router.post("/cancel")
async def cancel_billing(
    tenant: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Cancel the current subscription."""
    if current_user.tenant_slug != tenant:
        raise HTTPException(status_code=403, detail="Access denied")

    result = await db.execute(
        select(Subscription).where(Subscription.tenant_id == current_user.tenant_id)
    )
    sub = result.scalar_one_or_none()
    if sub is None or not sub.paypal_subscription_id:
        raise HTTPException(status_code=404, detail="No active subscription")

    try:
        await cancel_subscription(sub.paypal_subscription_id)
    except Exception:
        pass  # If PayPal call fails, still cancel locally

    sub.status = "cancelled"
    await db.commit()
    return {"ok": True, "message": "Subscription cancelled"}
```

---

## Phase 6: Tests

### Task 8: Write tests

**Files:**
- Create: `backend/tests/conftest.py`
- Create: `backend/tests/test_auth.py`
- Create: `backend/tests/test_kb.py`
- Create: `backend/tests/test_chat.py`

**Step 1: Write `backend/tests/conftest.py`**

```python
import asyncio
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from app.database import Base, get_db
from app.main import app

# Use SQLite for tests
TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"

test_engine = create_async_engine(TEST_DATABASE_URL, echo=False)
TestSessionLocal = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)


async def override_get_db():
    async with TestSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(scope="function")
async def db_session():
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with TestSessionLocal() as session:
        yield session
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture(scope="function")
async def client(db_session):
    app.dependency_overrides[get_db] = override_get_db
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as ac:
        yield ac
    app.dependency_overrides.clear()
```

**Step 2: Write `backend/tests/test_auth.py`**

```python
import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_register(client: AsyncClient):
    response = await client.post(
        "/auth/register",
        json={
            "email": "alex@example.com",
            "password": "securepass123",
            "full_name": "Alex Smith",
            "company_name": "Acme Corp",
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"


@pytest.mark.asyncio
async def test_register_duplicate_email(client: AsyncClient):
    payload = {
        "email": "dup@example.com",
        "password": "securepass123",
        "full_name": "Alex",
        "company_name": "Acme",
    }
    await client.post("/auth/register", json=payload)
    response = await client.post("/auth/register", json=payload)
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_login(client: AsyncClient):
    # Register first
    await client.post(
        "/auth/register",
        json={
            "email": "login@example.com",
            "password": "securepass123",
            "full_name": "Alex",
            "company_name": "LoginTest",
        },
    )
    # Login
    response = await client.post(
        "/auth/login",
        json={"email": "login@example.com", "password": "securepass123"},
    )
    assert response.status_code == 200
    assert "access_token" in response.json()


@pytest.mark.asyncio
async def test_login_wrong_password(client: AsyncClient):
    await client.post(
        "/auth/register",
        json={
            "email": "wrong@example.com",
            "password": "securepass123",
            "full_name": "Alex",
            "company_name": "WrongTest",
        },
    )
    response = await client.post(
        "/auth/login",
        json={"email": "wrong@example.com", "password": "wrongpassword"},
    )
    assert response.status_code == 401
```

**Step 3: Write `backend/tests/test_kb.py`**

```python
import pytest
from httpx import AsyncClient


async def get_auth_token(client: AsyncClient, email: str = "kb@example.com") -> str:
    await client.post(
        "/auth/register",
        json={
            "email": email,
            "password": "securepass123",
            "full_name": "KB Tester",
            "company_name": "KBTestCo",
        },
    )
    login = await client.post(
        "/auth/login",
        json={"email": email, "password": "securepass123"},
    )
    return login.json()["access_token"]


@pytest.mark.asyncio
async def test_add_document(client: AsyncClient):
    token = await get_auth_token(client, "kb_add@example.com")
    response = await client.post(
        "/KBTestCo/kb/",
        json={
            "title": "Vacation Policy",
            "content": "Employees receive 20 days of paid vacation per year. " * 5,
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["title"] == "Vacation Policy"
    assert data["char_count"] > 50


@pytest.mark.asyncio
async def test_add_document_too_short(client: AsyncClient):
    token = await get_auth_token(client, "kb_short@example.com")
    response = await client.post(
        "/KBTestCo/kb/",
        json={"title": "Short", "content": "Too short"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_list_documents(client: AsyncClient):
    token = await get_auth_token(client, "kb_list@example.com")
    # Add a doc first
    await client.post(
        "/KBTestCo/kb/",
        json={
            "title": "Handbook",
            "content": "Company handbook content goes here. " * 5,
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    response = await client.get(
        "/KBTestCo/kb/",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["total"] >= 1
    assert len(data["documents"]) >= 1


@pytest.mark.asyncio
async def test_delete_document(client: AsyncClient):
    token = await get_auth_token(client, "kb_del@example.com")
    add = await client.post(
        "/KBTestCo/kb/",
        json={
            "title": "To Delete",
            "content": "This document will be deleted. " * 5,
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    doc_id = add.json()["id"]
    response = await client.delete(
        f"/KBTestCo/kb/{doc_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    assert response.json()["ok"] is True
```

**Step 4: Run tests**

```bash
cd /root/hr-faq-bot/backend && .venv/bin/python -m pytest tests/ -v
```

Expected: All tests pass

---

## Phase 7: HTML UI Pages

### Task 9: Create dashboard and chat HTML pages

**Files:**
- Create: `backend/app/templates/login.html`
- Create: `backend/app/templates/dashboard.html`
- Create: `backend/app/templates/chat.html`
- Modify: `backend/app/main.py` (add static file routes)

**Step 1: Add HTML routes to `backend/app/main.py`**

```python
from fastapi import FastAPI, Response
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pathlib import Path

from app.routers import auth, kb, chat, billing

app = FastAPI(title="AlterZahen")

# Mount static files
app.mount("/static", StaticFiles(directory="app/templates"), name="static")

# Include API routers
app.include_router(auth.router)
app.include_router(kb.router)
app.include_router(chat.router)
app.include_router(billing.router)

BASE_DIR = Path(__file__).parent
TEMPLATES_DIR = BASE_DIR / "app" / "templates"


@app.get("/")
async def root():
    return RedirectResponse(url="/login")


@app.get("/login")
async def login_page():
    return FileResponse(TEMPLATES_DIR / "login.html")


@app.get("/{tenant}")
async def dashboard_or_redirect(tenant: str):
    # Check if it's an API route or a page
    # If no matching API route, serve dashboard
    return FileResponse(TEMPLATES_DIR / "dashboard.html")


@app.get("/{tenant}/chat")
async def chat_page(tenant: str):
    return FileResponse(TEMPLATES_DIR / "chat.html")
```

**Step 2: Write `backend/app/templates/login.html`**

Minimal login page — email, password, company name (for register). Single HTML file with embedded CSS + JS fetch calls to `/auth/register` and `/auth/login`. On success, redirect to `/{tenant}`.

**Step 3: Write `backend/app/templates/dashboard.html`**

KB management UI — list documents, add document form (title + textarea), delete buttons. Fetches from `/{tenant}/kb/`. Uses JWT from localStorage.

**Step 4: Write `backend/app/templates/chat.html`**

Chat widget UI — message input, chat history, send button. Fetches from `/{tenant}/chat/ask`. Shows sources below answer.

---

## Phase 8: Deployment

### Task 10: Update Procfile and environment setup

**Files:**
- Modify: `backend/Procfile`
- Create: `backend/.env.example`

**Step 1: Write `backend/Procfile`**

```
web: cd backend && gunicorn app.main:app --workers 2 --bind 0.0.0.0:$PORT --access-logfile -
```

**Step 2: Write `backend/.env.example`**

```
DATABASE_URL=postgresql+asyncpg://user:password@host:5432/alterzahen
SECRET_KEY=generate-a-random-secret-key-here
GROQ_API_KEY=your-groq-api-key
PAYPAL_CLIENT_ID=your-paypal-client-id
PAYPAL_CLIENT_SECRET=your-paypal-client-secret
PAYPAL_MODE=sandbox
APP_URL=https://your-domain.com
PRICE_ID=P-XXXXXXXXXXXXXXXX
```

**Step 3: Commit all**

```bash
git add backend/ && git commit -m "feat: multi-tenant SaaS foundation — FastAPI, PostgreSQL, PayPal, JWT"
```

---

## Verification Checklist

- [ ] `pytest tests/ -v` passes (100%)
- [ ] `/auth/register` creates tenant + user + subscription record
- [ ] `/auth/login` returns JWT
- [ ] `/{tenant}/kb/` CRUD works with auth
- [ ] `/{tenant}/chat/ask` returns AI answer with KB context
- [ ] PayPal subscription flow works (sandbox)
- [ ] Deploy to Render with PostgreSQL add-on
- [ ] Marketing landing page on Vercel/Netlify

---

## Pending Decisions

1. **PayPal product/plan setup** — You need to create a $29/mo recurring product in your PayPal sandbox dashboard and get the `PRICE_ID` (starts with `P-`)
2. **Marketing domain** — Where should the public landing page live? (`alterzahen.com` on Vercel?)
3. **Tenant slug uniqueness** — If two companies named "Acme" sign up, the second gets a conflict. We should auto-append a suffix. (implement in Task 3 router)

