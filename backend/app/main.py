from contextlib import asynccontextmanager
from fastapi import FastAPI, Response, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse, FileResponse, JSONResponse
from fastapi.responses import RedirectResponse, FileResponse, JSONResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.exceptions import RequestValidationError
from fastapi import HTTPException
from pathlib import Path
from datetime import datetime, timezone, timedelta

from app.services.structured_logger import log_event

from app.config import get_settings
from app.database import engine, Base, AsyncSessionLocal
from app.services.auth import create_access_token, hash_password
from app.models import Tenant, User, Subscription, Document
from app.routers import auth, kb, chat, billing, leads, demo
from app.routers import admin
from app.routers import escalations

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
import json

settings = get_settings()


_db_ready: bool = False
_db_error: str | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _db_ready, _db_error
    app.state.db_ready = False
    app.state.db_error = None

    # Startup (best-effort)
    attempts = 3
    last_err: str | None = None
    for i in range(attempts):
        try:
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            _db_ready = True
            app.state.db_ready = True
            _db_error = None
            app.state.db_error = None
            last_err = None
            break
        except Exception as e:
            last_err = str(e)
            _db_ready = False
            app.state.db_ready = False
            _db_error = last_err
            app.state.db_error = last_err

            # brief backoff, bounded
            if i < attempts - 1:
                import asyncio

                await asyncio.sleep(1.5 * (i + 1))

    if not _db_ready:
        log_event(event="db_startup_unavailable", severity="high", attempts=attempts, error=last_err)

    async def ensure_demo_data() -> None:
        if not getattr(app.state, "db_ready", False):
            return

        demo_slug = "demo"
        demo_email = "demo@replyiq.local"
        demo_password = "demo-password"

        async with AsyncSessionLocal() as session:
            tenant_result = await session.execute(select(Tenant).where(Tenant.slug == demo_slug))
            demo_tenant = tenant_result.scalar_one_or_none()

            if demo_tenant is None:
                demo_tenant = Tenant(name="Demo Company", slug=demo_slug)
                session.add(demo_tenant)
                await session.flush()

            sub_result = await session.execute(
                select(Subscription).where(Subscription.tenant_id == demo_tenant.id)
            )
            subscription = sub_result.scalar_one_or_none()

            if subscription is None:
                subscription = Subscription(
                    tenant_id=demo_tenant.id,
                    plan="starter",
                    price=99,
                    status="active",
                    current_period_end=datetime.now(timezone.utc) + timedelta(days=365),
                )
                session.add(subscription)
            else:
                subscription.status = "active"
                subscription.plan = subscription.plan or "starter"
                subscription.price = subscription.price if subscription.price is not None else 99
                if subscription.current_period_end is None:
                    subscription.current_period_end = datetime.now(timezone.utc) + timedelta(days=365)

            user_result = await session.execute(select(User).where(User.email == demo_email))
            demo_user = user_result.scalar_one_or_none()
            if demo_user is None:
                demo_user = User(
                    email=demo_email,
                    password_hash=hash_password(demo_password),
                    full_name="Demo User",
                    tenant_id=demo_tenant.id,
                    is_owner=True,
                    is_active=True,
                )
                session.add(demo_user)
            else:
                demo_user.tenant_id = demo_tenant.id
                demo_user.is_owner = True
                demo_user.is_active = True

            docs_result = await session.execute(select(Document).where(Document.tenant_id == demo_tenant.id))
            existing_docs = docs_result.scalars().first()

            if existing_docs is None:
                kb_path = Path(__file__).parent.parent / "knowledge_base.json"
                kb = json.loads(kb_path.read_text(encoding="utf-8"))
                docs = []
                for d in kb.get("documents", []):
                    content = d.get("content", "")
                    docs.append(
                        Document(
                            tenant_id=demo_tenant.id,
                            title=d.get("title", "Untitled"),
                            content=content,
                            source_url=d.get("source") or None,
                            char_count=len(content),
                        )
                    )
                session.add_all(docs)

            try:
                await session.commit()
            except IntegrityError:
                await session.rollback()

    await ensure_demo_data()

    # Expose readiness + last error to dependencies
    app.state.db_ready = bool(_db_ready)
    app.state.db_error = _db_error

    yield

    # Shutdown
    await engine.dispose()


app = FastAPI(title="RelyIQ API", version="1.0.0", lifespan=lifespan)

_allowed_origins = [o.strip() for o in settings.ALLOWED_ORIGINS.split(",")]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include API routers
app.include_router(auth.router)
app.include_router(kb.router)
app.include_router(chat.router)
app.include_router(billing.router)
app.include_router(leads.router)
app.include_router(demo.router)
app.include_router(admin.router)
app.include_router(escalations.router)


# ─── Structured error responses ─────────────────────────────────────────

@app.exception_handler(HTTPException)
async def structured_http_exception_handler(request: Request, exc: HTTPException):
    log_event(
        event="http_exception",
        severity="medium" if exc.status_code < 500 else "high",
        path=request.url.path,
        status_code=exc.status_code,
    )
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": {
                "code": "http_error",
                "message": exc.detail,
                "status": exc.status_code,
            },
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
    )


@app.exception_handler(RequestValidationError)
async def structured_validation_exception_handler(request: Request, exc: RequestValidationError):
    log_event(event="validation_error", severity="medium", path=request.url.path)
    return JSONResponse(
        status_code=422,
        content={
            "error": {
                "code": "validation_error",
                "message": "Request validation failed",
                "details": exc.errors(),
            },
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
    )


# Paths
BASE_DIR = Path(__file__).parent.parent          # → backend/
TEMPLATES_DIR = BASE_DIR / "app" / "templates"   # → backend/app/templates


# ─── Health ──────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {
        "status": "ok",
        "app": "relyiq",
        "db": _db_ready,
        "db_error": getattr(app.state, "db_error", None),
    }


# ─── Marketing / Landing Pages ───────────────────────────────────────────────

@app.get("/")
async def root():
    return FileResponse(TEMPLATES_DIR / "index.html")


@app.get("/login")
async def login_page():
    return FileResponse(TEMPLATES_DIR / "login.html")


@app.get("/presell")
async def presell_page():
    return FileResponse(TEMPLATES_DIR / "presell.html")


@app.get("/product")
async def product_page():
    return FileResponse(TEMPLATES_DIR / "product.html")
async def product_page(request: Request):
    product_html_path = BASE_DIR / "product.html"
    html = product_html_path.read_text(encoding="utf-8")

    # If DB isn't ready, keep the UI as the static client-side demo.
    if not getattr(request.app.state, "db_ready", False):
        return HTMLResponse(
            html.replace("__DEMO_TENANT__", "demo").replace("__DEMO_TOKEN__", "")
        )

    demo_slug = "demo"
    demo_email = "demo@replyiq.local"

    async with AsyncSessionLocal() as session:
        tenant_result = await session.execute(select(Tenant).where(Tenant.slug == demo_slug))
        demo_tenant = tenant_result.scalar_one_or_none()
        user_result = await session.execute(select(User).where(User.email == demo_email))
        demo_user = user_result.scalar_one_or_none()

        if demo_tenant is None or demo_user is None:
            return HTMLResponse(
                html.replace("__DEMO_TENANT__", demo_slug).replace("__DEMO_TOKEN__", "")
            )

        token = create_access_token(
            data={"user_id": demo_user.id, "tenant_slug": demo_tenant.slug},
            expires_delta=timedelta(minutes=30),
        )

    # Inject short-lived JWT so the landing demo can call authenticated APIs.
    token_safe = token.replace("'", "\\'")
    html = html.replace("__DEMO_TENANT__", demo_slug).replace("__DEMO_TOKEN__", token_safe)
    return HTMLResponse(html)


@app.get("/success")
async def success_page():
    return FileResponse(TEMPLATES_DIR / "success.html")


@app.get("/index")
async def index_page():
    return FileResponse(BASE_DIR / "index.html")


# ─── App Pages ────────────────────────────────────────────────────────────────

@app.get("/{tenant}/dashboard")
async def dashboard_page(tenant: str):
    return FileResponse(TEMPLATES_DIR / "dashboard.html")


@app.get("/{tenant}/chat")
async def chat_page(tenant: str):
    return FileResponse(TEMPLATES_DIR / "chat.html")


@app.get("/{tenant}/billing/success")
async def billing_success(tenant: str):
    return FileResponse(TEMPLATES_DIR / "dashboard.html")


@app.get("/{tenant}/billing/cancel")
async def billing_cancel(tenant: str):
    return RedirectResponse(url=f"/{tenant}/dashboard")
