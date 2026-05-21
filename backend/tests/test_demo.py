"""Tests for the demo router."""
import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_demo_track(client: AsyncClient, get_auth_token: str):
    """Demo track endpoint records a funnel event."""
    headers = {"Authorization": f"Bearer {get_auth_token}"}
    me_resp = await client.get("/auth/me", headers=headers)
    tenant_slug = me_resp.json()["tenant_slug"]

    response = await client.post(f"/{tenant_slug}/demo/track", headers=headers)
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_demo_track_requires_auth(client: AsyncClient):
    """Demo track requires authentication."""
    response = await client.post("/test-tenant/demo/track")
    assert response.status_code == 401
