from contextlib import asynccontextmanager
from fastapi import FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path

from app.config import get_settings
from app.database import engine, Base
from app.routers import auth, kb, chat, billing
from app.routers import admin

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    # Shutdown
    await engine.dispose()


app = FastAPI(title="AlterZahen API", version="1.0.0", lifespan=lifespan)

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
app.include_router(admin.router)

# Paths
BASE_DIR = Path(__file__).parent.parent          # → backend/
TEMPLATES_DIR = BASE_DIR / "app" / "templates"   # → backend/app/templates
STATIC_DIR = BASE_DIR / "static"                  # → backend/static

# Mount static files (create static/ dir if needed)
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


# ─── Health ──────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "ok", "app": "alterzahen"}


# ─── Marketing / Landing Pages ───────────────────────────────────────────────

@app.get("/")
async def root():
    return RedirectResponse(url="/login")


@app.get("/login")
async def login_page():
    return FileResponse(TEMPLATES_DIR / "login.html")


@app.get("/presell")
async def presell_page():
    return FileResponse(BASE_DIR / "presell.html")


@app.get("/product")
async def product_page():
    return FileResponse(BASE_DIR / "product.html")


@app.get("/success")
async def success_page():
    return FileResponse(BASE_DIR / "success.html")


@app.get("/index")
async def index_page():
    return RedirectResponse(url="/presell")


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
