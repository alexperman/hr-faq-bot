from contextlib import asynccontextmanager
from fastapi import FastAPI, Response, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse, FileResponse, JSONResponse
from fastapi.exceptions import RequestValidationError
from fastapi import HTTPException
from pathlib import Path
from datetime import datetime, timezone

from app.services.structured_logger import log_event

from app.config import get_settings
from app.database import engine, Base
from app.routers import auth, kb, chat, billing, leads
from app.routers import admin
from app.routers import escalations

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
