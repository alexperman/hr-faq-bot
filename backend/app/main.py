from fastapi import FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse, FileResponse
from pathlib import Path

from app.config import get_settings
from app.database import engine, Base
from app.routers import auth, kb, chat, billing

settings = get_settings()

app = FastAPI(title="AlterZahen API", version="1.0.0")

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


@app.on_event("startup")
async def startup():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


BASE_DIR = Path(__file__).parent.parent
TEMPLATES_DIR = BASE_DIR / "app" / "templates"


@app.get("/health")
async def health():
    return {"status": "ok", "app": "alterzahen"}


@app.get("/")
async def root():
    return RedirectResponse(url="/login")


@app.get("/login")
async def login_page():
    return FileResponse(TEMPLATES_DIR / "login.html")


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
