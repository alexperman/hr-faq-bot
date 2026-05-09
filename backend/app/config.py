from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache
from pydantic import field_validator


class Settings(BaseSettings):
    # Database
    _DEFAULT_DATABASE_URL: str = "postgresql+asyncpg://user:pass@localhost:5432/alterzahen"
    DATABASE_URL: str = _DEFAULT_DATABASE_URL
    ALLOWED_ORIGINS: str = "*"  # Comma-separated list in production

    # JWT
    SECRET_KEY: str = "change-me-in-production-use-openssl-rand-base64-32"
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
    PRICE_ID: str = "P-XXXXXXXXXXXXXXXX"  # fallback PayPal product/plan ID

    # Optional per-plan PayPal price IDs (used when set)
    PRICE_ID_STARTER: str = ""
    PRICE_ID_GROWTH: str = ""
    PRICE_ID_ENTERPRISE: str = ""

    @field_validator("DATABASE_URL", mode="before")
    @classmethod
    def _normalize_database_url(cls, v: str | None) -> str:
        if v is None:
            return cls._DEFAULT_DATABASE_URL
        if isinstance(v, str):
            v = v.strip()
        if not v:
            return cls._DEFAULT_DATABASE_URL

        # Render Postgres commonly provides postgresql://...; convert to async driver.
        if v.startswith("postgres://"):
            return "postgresql+asyncpg://" + v[len("postgres://"):]
        if v.startswith("postgresql://"):
            return "postgresql+asyncpg://" + v[len("postgresql://"):]

        # Basic guardrail for clearly invalid values.
        if "://" not in v:
            raise ValueError("DATABASE_URL must include a scheme, e.g. postgresql+asyncpg://user:pass@host:5432/db")

        return v

    model_config = SettingsConfigDict(env_file=".env")


@lru_cache
def get_settings() -> Settings:
    return Settings()
