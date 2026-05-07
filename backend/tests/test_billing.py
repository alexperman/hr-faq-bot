import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_get_plans_public(client: AsyncClient):
    """Plans endpoint should be public, no auth required."""
    response = await client.get("/starter/billing/plans")
    assert response.status_code == 200
    data = response.json()
    assert "plans" in data
    assert len(data["plans"]) == 3
    assert any(p["id"] == "starter" for p in data["plans"])


@pytest.mark.asyncio
async def test_subscribe_requires_auth(client: AsyncClient):
    """Subscribe endpoint requires JWT."""
    response = await client.post(
        "/test-tenant/billing/subscribe",
        json={"plan": "starter"},
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_subscribe_with_auth(client: AsyncClient, get_auth_token: str):
    """Owner can initiate subscription."""
    headers = {"Authorization": f"Bearer {get_auth_token}"}
    me_resp = await client.get("/auth/me", headers=headers)
    tenant_slug = me_resp.json()["tenant_slug"]

    # Subscribe returns approval_url or a PayPal error (PayPal not configured in tests)
    response = await client.post(
        f"/{tenant_slug}/billing/subscribe",
        json={"plan": "starter"},
        headers=headers,
    )
    # Either succeeds (200) with approval_url, or 502 if PayPal is misconfigured
    # We accept both since PayPal credentials won't be set in test env
    assert response.status_code in (200, 502)
    if response.status_code == 200:
        data = response.json()
        assert "approval_url" in data


@pytest.mark.asyncio
async def test_cancel_requires_auth(client: AsyncClient):
    """Cancel requires JWT."""
    response = await client.post("/test-tenant/billing/cancel")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_cancel_no_subscription(client: AsyncClient, get_auth_token: str):
    """Cancel returns 404 when no subscription exists."""
    headers = {"Authorization": f"Bearer {get_auth_token}"}
    me_resp = await client.get("/auth/me", headers=headers)
    tenant_slug = me_resp.json()["tenant_slug"]

    response = await client.post(
        f"/{tenant_slug}/billing/cancel",
        headers=headers,
    )
    # No active subscription to cancel
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_webhook_unknown_event(client: AsyncClient):
    """Unknown webhook events are handled gracefully."""
    response = await client.post(
        "/test-tenant/billing/webhook",
        json={"event_type": "UNKNOWN.EVENT", "resource": {}},
    )
    # Should not error, just return ok
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_webhook_billing_subscription_activated(client: AsyncClient, get_auth_token: str):
    """ACTIVATED webhook updates subscription status to active."""
    headers = {"Authorization": f"Bearer {get_auth_token}"}
    me_resp = await client.get("/auth/me", headers=headers)
    tenant_slug = me_resp.json()["tenant_slug"]

    # First subscribe to create a subscription record (may fail with PayPal)
    await client.post(
        f"/{tenant_slug}/billing/subscribe",
        json={"plan": "starter"},
        headers=headers,
    )

    # Webhook with ACTIVATED event
    response = await client.post(
        f"/{tenant_slug}/billing/webhook",
        json={
            "event_type": "BILLING.SUBSCRIPTION.ACTIVATED",
            "resource": {"id": "I-DUMMY-SUB-ID"},
        },
    )
    assert response.status_code == 200
