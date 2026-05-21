"""Tests for the admin router."""
import os
import pytest
from httpx import AsyncClient

ADMIN_KEY = "test-admin-key"


@pytest.fixture(autouse=True)
def set_admin_key(monkeypatch):
    """Set ADMIN_API_KEY for all admin tests."""
    monkeypatch.setenv("ADMIN_API_KEY", ADMIN_KEY)
    # Clear cached settings so new env var is picked up
    from app.config import get_settings
    get_settings.cache_clear()
    # Also patch the module-level settings in admin router
    from app.routers import admin as admin_mod
    admin_mod.settings = get_settings()
    yield
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_admin_health_ok(client: AsyncClient):
    """Admin health endpoint returns ok with valid token."""
    headers = {"Authorization": f"Bearer {ADMIN_KEY}"}
    response = await client.get("/admin/health", headers=headers)
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_admin_health_unauthorized(client: AsyncClient):
    """Admin health rejects invalid token."""
    headers = {"Authorization": "Bearer wrong-key"}
    response = await client.get("/admin/health", headers=headers)
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_admin_health_no_token(client: AsyncClient):
    """Admin health rejects missing token."""
    response = await client.get("/admin/health")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_system_health(client: AsyncClient):
    """System health returns comprehensive status."""
    headers = {"Authorization": f"Bearer {ADMIN_KEY}"}
    response = await client.get("/admin/system/health", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert "ok" in data
    assert "db" in data
    assert "paypal" in data
    assert "kb" in data
    assert "rate_limit" in data
    assert "tenants" in data


@pytest.mark.asyncio
async def test_system_logs(client: AsyncClient):
    """System logs returns structured log data."""
    headers = {"Authorization": f"Bearer {ADMIN_KEY}"}
    response = await client.get("/admin/system/logs", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert "recent_webhook_events" in data
    assert "recent_rate_limit_exceeds" in data


@pytest.mark.asyncio
async def test_system_stats(client: AsyncClient):
    """System stats returns aggregate statistics."""
    headers = {"Authorization": f"Bearer {ADMIN_KEY}"}
    response = await client.get("/admin/system/stats", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert "tenants_total" in data
    assert "documents_total" in data
    assert "subscriptions_by_status" in data
    assert "paypal" in data


@pytest.mark.asyncio
async def test_deploy_status(client: AsyncClient):
    """Deploy status returns deployment info."""
    headers = {"Authorization": f"Bearer {ADMIN_KEY}"}
    response = await client.get("/admin/deploy/status", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert "app_start_time" in data


@pytest.mark.asyncio
async def test_paypal_status(client: AsyncClient):
    """PayPal status returns webhook info."""
    headers = {"Authorization": f"Bearer {ADMIN_KEY}"}
    response = await client.get("/admin/paypal/status", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert "paypal_mode" in data
    assert "webhook_id_configured" in data
    assert "latest_webhook" in data


@pytest.mark.asyncio
async def test_tenants_summary(client: AsyncClient):
    """Tenants summary returns aggregate tenant data."""
    headers = {"Authorization": f"Bearer {ADMIN_KEY}"}
    response = await client.get("/admin/tenants/summary", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert "tenants_total" in data
    assert "active_tenants" in data
    assert "active_subscriptions" in data


@pytest.mark.asyncio
async def test_kb_reindex_requires_approval(client: AsyncClient):
    """KB reindex requires X-Approval header."""
    headers = {"Authorization": f"Bearer {ADMIN_KEY}"}
    response = await client.post("/admin/kb/reindex", headers=headers)
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_kb_reindex_with_approval(client: AsyncClient):
    """KB reindex succeeds with approval header."""
    headers = {"Authorization": f"Bearer {ADMIN_KEY}", "X-Approval": "true"}
    response = await client.post("/admin/kb/reindex", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "noop"


@pytest.mark.asyncio
async def test_leads_recent(client: AsyncClient):
    """Leads recent returns lead data."""
    headers = {"Authorization": f"Bearer {ADMIN_KEY}"}
    response = await client.get("/admin/leads/recent", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert "leads" in data
    assert isinstance(data["leads"], list)


@pytest.mark.asyncio
async def test_funnel_recent(client: AsyncClient):
    """Funnel recent returns event data."""
    headers = {"Authorization": f"Bearer {ADMIN_KEY}"}
    response = await client.get("/admin/funnel/recent", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert "events" in data
    assert isinstance(data["events"], list)
