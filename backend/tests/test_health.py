"""Tests for the health endpoint and main app routes."""
import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_health_endpoint(client: AsyncClient):
    """Health endpoint returns status."""
    response = await client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["app"] == "relyiq"
    assert "db" in data


@pytest.mark.asyncio
async def test_root_page(client: AsyncClient):
    """Root page serves HTML."""
    response = await client.get("/")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_login_page(client: AsyncClient):
    """Login page serves HTML."""
    response = await client.get("/login")
    assert response.status_code == 200
