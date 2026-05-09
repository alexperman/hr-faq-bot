import os
import asyncio
from typing import AsyncGenerator
from datetime import datetime, timezone, timedelta

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import declarative_base
from sqlalchemy import select

# Set test database before importing app modules
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///file::memory:?cache=shared&uri=true"
os.environ["SECRET_KEY"] = "test-secret-key-for-testing-only"
os.environ["GROQ_API_KEY"] = "test-groq-api-key"

from app.main import app
from app.database import Base, get_db
from app.models import User, Subscription


# Create a shared in-memory SQLite engine for tests
test_engine = create_async_engine(
    "sqlite+aiosqlite:///file::memory:?cache=shared&uri=true",
    echo=False,
    connect_args={"check_same_thread": False},
)

TestingSessionLocal = async_sessionmaker(
    test_engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(scope="function")
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """Create tables and yield a test database session, then drop all tables."""
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with TestingSessionLocal() as session:
        yield session

    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture(scope="function")
async def client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """Provide an async HTTP client for the FastAPI app with test DB override."""

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def get_auth_token(client: AsyncClient, db_session: AsyncSession) -> str:
    """Register a user and return a JWT with an ACTIVE subscription (for MVP option B tests)."""

    register_payload = {
        "email": "testuser@example.com",
        "password": "testpassword123",
        "full_name": "Test User",
        "company_name": "Test Company",
    }

    response = await client.post("/auth/register", json=register_payload)
    assert response.status_code == 200, f"Registration failed: {response.text}"
    data = response.json()

    # Activate subscription so KB/chat endpoints are reachable.
    user_result = await db_session.execute(
        select(User).where(User.email == register_payload["email"])
    )
    user = user_result.scalar_one()

    sub_result = await db_session.execute(
        select(Subscription).where(Subscription.tenant_id == user.tenant_id)
    )
    subscription = sub_result.scalar_one_or_none()

    if subscription is None:
        subscription = Subscription(
            tenant_id=user.tenant_id,
            status="active",
            plan=None,
            price=None,
            paypal_subscription_id=None,
        )
        db_session.add(subscription)
        await db_session.flush()
    else:
        subscription.status = "active"
    # Keep paypal_subscription_id unset so billing cancel tests behave as "no active PayPal subscription".
    subscription.current_period_end = datetime.now(timezone.utc) + timedelta(days=30)

    await db_session.commit()

    return data["access_token"]
