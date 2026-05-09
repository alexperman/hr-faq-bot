from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache


class Settings(BaseSettings):
    # Database
    DATABASE_URL: str = "postgresql+asyncpg://user:pass@localhost:5432/alterzahen"
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

    model_config = SettingsConfigDict(env_file=".env")


@lru_cache
def get_settings() -> Settings:
    return Settings()
