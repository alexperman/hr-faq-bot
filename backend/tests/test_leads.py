"""Tests for the leads router."""
import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_subscribe_lead(client: AsyncClient):
    """Lead subscription creates a new lead."""
    response = await client.post(
        "/leads/subscribe",
        json={"email": "newlead@example.com", "source": "landing"},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_subscribe_lead_duplicate(client: AsyncClient):
    """Duplicate lead subscription is idempotent."""
    payload = {"email": "duplead@example.com", "source": "landing"}
    await client.post("/leads/subscribe", json=payload)

    response = await client.post("/leads/subscribe", json=payload)
    assert response.status_code == 200
    assert response.json()["status"] == "already_registered"


@pytest.mark.asyncio
async def test_subscribe_lead_invalid_email(client: AsyncClient):
    """Invalid email returns validation error."""
    response = await client.post(
        "/leads/subscribe",
        json={"email": "not-an-email", "source": "landing"},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_subscribe_lead_default_source(client: AsyncClient):
    """Lead with no source defaults to 'landing'."""
    response = await client.post(
        "/leads/subscribe",
        json={"email": "defaultsource@example.com"},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
