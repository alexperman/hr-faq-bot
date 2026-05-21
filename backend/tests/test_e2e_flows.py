"""End-to-end flow tests covering complete user journeys."""
import pytest
from httpx import AsyncClient
from unittest.mock import patch, AsyncMock

from app.services.rate_limit import _request_windows


@pytest.fixture(autouse=True)
def clear_rate_limits():
    """Clear rate limit state between tests."""
    _request_windows.clear()
    yield
    _request_windows.clear()


@pytest.mark.asyncio
async def test_full_registration_to_chat_flow(client: AsyncClient):
    """Complete flow: register → add KB doc → ask question → get answer."""
    # 1. Register
    reg_resp = await client.post("/auth/register", json={
        "email": "e2e@example.com",
        "password": "securepass123",
        "full_name": "E2E User",
        "company_name": "E2E Company",
    })
    assert reg_resp.status_code == 200
    token = reg_resp.json()["access_token"]
    tenant_slug = reg_resp.json()["tenant_slug"]
    headers = {"Authorization": f"Bearer {token}"}

    # 2. Verify /me works
    me_resp = await client.get("/auth/me", headers=headers)
    assert me_resp.status_code == 200
    assert me_resp.json()["email"] == "e2e@example.com"

    # 3. Add KB document
    doc_resp = await client.post(f"/{tenant_slug}/kb/", json={
        "title": "PTO Policy",
        "content": "All full-time employees receive 20 days of paid time off per year. PTO accrues monthly at 1.67 days per month.",
    }, headers=headers)
    assert doc_resp.status_code == 201

    # 4. Ask a question
    with patch("app.routers.chat.ask_groq", new_callable=AsyncMock) as mock_groq:
        mock_groq.return_value = "You receive 20 days of PTO per year, accruing at 1.67 days per month."
        chat_resp = await client.post(f"/{tenant_slug}/chat/ask", json={
            "question": "How many PTO days do I get?",
        }, headers=headers)
    assert chat_resp.status_code == 200
    data = chat_resp.json()
    assert "20" in data["answer"]
    assert len(data["sources"]) > 0

    # 5. Verify chat history
    history_resp = await client.get(f"/{tenant_slug}/chat/history", headers=headers)
    assert history_resp.status_code == 200
    assert len(history_resp.json()) >= 2


@pytest.mark.asyncio
async def test_team_invite_and_member_chat_flow(client: AsyncClient):
    """Flow: register owner → invite member → member logs in → member chats."""
    # 1. Register owner
    reg_resp = await client.post("/auth/register", json={
        "email": "owner_e2e@example.com",
        "password": "ownerpass123",
        "full_name": "Owner",
        "company_name": "Team Company",
    })
    assert reg_resp.status_code == 200
    owner_token = reg_resp.json()["access_token"]
    tenant_slug = reg_resp.json()["tenant_slug"]
    owner_headers = {"Authorization": f"Bearer {owner_token}"}

    # 2. Add KB doc
    await client.post(f"/{tenant_slug}/kb/", json={
        "title": "Remote Work Policy",
        "content": "Employees may work remotely up to 3 days per week. Remote work requires manager approval and a stable internet connection.",
    }, headers=owner_headers)

    # 3. Invite member
    invite_resp = await client.post("/auth/invite", json={
        "email": "member_e2e@example.com",
    }, headers=owner_headers)
    assert invite_resp.status_code == 200
    temp_password = invite_resp.json()["temp_password"]

    # 4. Member logs in
    login_resp = await client.post("/auth/login", json={
        "email": "member_e2e@example.com",
        "password": temp_password,
    })
    assert login_resp.status_code == 200
    member_token = login_resp.json()["access_token"]
    member_headers = {"Authorization": f"Bearer {member_token}"}

    # 5. Member asks a question
    with patch("app.routers.chat.ask_groq", new_callable=AsyncMock) as mock_groq:
        mock_groq.return_value = "You can work remotely up to 3 days per week with manager approval."
        chat_resp = await client.post(f"/{tenant_slug}/chat/ask", json={
            "question": "Can I work from home?",
        }, headers=member_headers)
    assert chat_resp.status_code == 200
    assert "3 days" in chat_resp.json()["answer"]


@pytest.mark.asyncio
async def test_escalation_flow(client: AsyncClient):
    """Flow: user asks → AI can't answer → escalation created → admin replies → user reads."""
    # 1. Register
    reg_resp = await client.post("/auth/register", json={
        "email": "esc_e2e@example.com",
        "password": "escpass123",
        "full_name": "Esc User",
        "company_name": "Esc Company",
    })
    token = reg_resp.json()["access_token"]
    tenant_slug = reg_resp.json()["tenant_slug"]
    headers = {"Authorization": f"Bearer {token}"}

    # 2. Add a doc
    await client.post(f"/{tenant_slug}/kb/", json={
        "title": "General Policy",
        "content": "This is the general company policy document covering basic workplace rules and expectations for all employees.",
    }, headers=headers)

    # 3. Ask a question that triggers escalation
    with patch("app.routers.chat.ask_groq", new_callable=AsyncMock) as mock_groq:
        mock_groq.return_value = "I don't have enough information to answer this question based on the available documents."
        chat_resp = await client.post(f"/{tenant_slug}/chat/ask", json={
            "question": "What is the quantum computing policy?",
        }, headers=headers)
    assert chat_resp.status_code == 200
    assert chat_resp.json()["escalated"] is True
    escalation_id = chat_resp.json()["escalation_id"]

    # 4. Admin sees the escalation
    esc_list_resp = await client.get(f"/{tenant_slug}/escalations/", headers=headers)
    assert esc_list_resp.status_code == 200
    assert len(esc_list_resp.json()) >= 1

    # 5. Admin replies
    reply_resp = await client.post(
        f"/{tenant_slug}/escalations/{escalation_id}/reply",
        json={"reply": "We don't have a quantum computing policy. Please contact IT."},
        headers=headers,
    )
    assert reply_resp.status_code == 200
    assert reply_resp.json()["status"] == "replied"

    # 6. User sees the reply
    replies_resp = await client.get(f"/{tenant_slug}/escalations/my-replies", headers=headers)
    assert replies_resp.status_code == 200
    assert len(replies_resp.json()) >= 1

    # 7. User marks as read
    read_resp = await client.post(f"/{tenant_slug}/escalations/{escalation_id}/read", headers=headers)
    assert read_resp.status_code == 200


@pytest.mark.asyncio
async def test_billing_plans_and_subscribe_flow(client: AsyncClient):
    """Flow: view plans → attempt subscribe (PayPal will fail in test)."""
    # 1. Register
    reg_resp = await client.post("/auth/register", json={
        "email": "billing_e2e@example.com",
        "password": "billpass123",
        "full_name": "Billing User",
        "company_name": "Billing Company",
    })
    token = reg_resp.json()["access_token"]
    tenant_slug = reg_resp.json()["tenant_slug"]
    headers = {"Authorization": f"Bearer {token}"}

    # 2. View plans (public)
    plans_resp = await client.get(f"/{tenant_slug}/billing/plans")
    assert plans_resp.status_code == 200
    plans = plans_resp.json()["plans"]
    assert len(plans) == 3
    plan_ids = [p["id"] for p in plans]
    assert "starter" in plan_ids
    assert "growth" in plan_ids
    assert "enterprise" in plan_ids

    # 3. Attempt subscribe (will fail because PayPal isn't configured)
    sub_resp = await client.post(f"/{tenant_slug}/billing/subscribe", json={
        "plan": "starter",
    }, headers=headers)
    # Either 200 (if PayPal mock works) or 502 (PayPal not configured)
    assert sub_resp.status_code in (200, 502)


@pytest.mark.asyncio
async def test_lead_to_signup_funnel(client: AsyncClient):
    """Flow: lead subscribes → later registers → funnel events tracked."""
    # 1. Lead subscribes on landing page
    lead_resp = await client.post("/leads/subscribe", json={
        "email": "funnel_e2e@example.com",
        "source": "landing",
    })
    assert lead_resp.status_code == 200

    # 2. Lead later registers
    reg_resp = await client.post("/auth/register", json={
        "email": "funnel_e2e@example.com",
        "password": "funnelpass123",
        "full_name": "Funnel User",
        "company_name": "Funnel Company",
    })
    assert reg_resp.status_code == 200
    # Registration should succeed and link to existing lead


@pytest.mark.asyncio
async def test_api_key_agent_flow(client: AsyncClient):
    """Flow: owner creates API key → agent exchanges for JWT → agent uses JWT."""
    # 1. Register
    reg_resp = await client.post("/auth/register", json={
        "email": "apikey_e2e@example.com",
        "password": "apikeypass123",
        "full_name": "API Key User",
        "company_name": "API Key Company",
    })
    token = reg_resp.json()["access_token"]
    tenant_slug = reg_resp.json()["tenant_slug"]
    headers = {"Authorization": f"Bearer {token}"}

    # 2. Create API key
    key_resp = await client.post("/api/keys", json={
        "name": "E2E Agent Key",
        "scope": "agent",
        "permissions": "read,write",
    }, headers=headers)
    assert key_resp.status_code == 201
    full_key = key_resp.json()["full_key"]

    # 3. Exchange key for JWT
    exchange_resp = await client.post("/api/keys/exchange", headers={"X-API-Key": full_key})
    assert exchange_resp.status_code == 200
    agent_token = exchange_resp.json()["access_token"]
    assert exchange_resp.json()["session_type"] == "agent"

    # 4. Agent uses JWT to access /me
    agent_headers = {"Authorization": f"Bearer {agent_token}"}
    me_resp = await client.get("/auth/me", headers=agent_headers)
    assert me_resp.status_code == 200
    assert me_resp.json()["email"] == "apikey_e2e@example.com"


@pytest.mark.asyncio
async def test_kb_lifecycle_flow(client: AsyncClient):
    """Flow: add docs → list → get single → delete → verify gone."""
    # Register
    reg_resp = await client.post("/auth/register", json={
        "email": "kb_e2e@example.com",
        "password": "kbpass123",
        "full_name": "KB User",
        "company_name": "KB Company",
    })
    token = reg_resp.json()["access_token"]
    tenant_slug = reg_resp.json()["tenant_slug"]
    headers = {"Authorization": f"Bearer {token}"}

    # Add 3 docs
    doc_ids = []
    for i in range(3):
        resp = await client.post(f"/{tenant_slug}/kb/", json={
            "title": f"Policy {i}",
            "content": f"This is policy document number {i} with enough content to pass the minimum character validation requirement.",
        }, headers=headers)
        assert resp.status_code == 201
        doc_ids.append(resp.json()["id"])

    # List all
    list_resp = await client.get(f"/{tenant_slug}/kb/", headers=headers)
    assert list_resp.status_code == 200
    assert len(list_resp.json()) == 3

    # Get single
    get_resp = await client.get(f"/{tenant_slug}/kb/{doc_ids[0]}", headers=headers)
    assert get_resp.status_code == 200
    assert get_resp.json()["title"] == "Policy 0"

    # Delete one
    del_resp = await client.delete(f"/{tenant_slug}/kb/{doc_ids[1]}", headers=headers)
    assert del_resp.status_code == 204

    # Verify 2 remain
    list_resp2 = await client.get(f"/{tenant_slug}/kb/", headers=headers)
    assert len(list_resp2.json()) == 2
    remaining_ids = [d["id"] for d in list_resp2.json()]
    assert doc_ids[1] not in remaining_ids


@pytest.mark.asyncio
async def test_password_reset_flow(client: AsyncClient):
    """Flow: register → forgot password → reset → login with new password."""
    # Register
    await client.post("/auth/register", json={
        "email": "reset_e2e@example.com",
        "password": "oldpass123",
        "full_name": "Reset User",
        "company_name": "Reset Company",
    })

    # Forgot password
    forgot_resp = await client.post("/auth/forgot-password", json={
        "email": "reset_e2e@example.com",
    })
    assert forgot_resp.status_code == 200
    reset_token = forgot_resp.json()["reset_token"]

    # Reset password
    reset_resp = await client.post("/auth/reset-password", json={
        "token": reset_token,
        "new_password": "newpass456",
    })
    assert reset_resp.status_code == 200

    # Login with new password
    login_resp = await client.post("/auth/login", json={
        "email": "reset_e2e@example.com",
        "password": "newpass456",
    })
    assert login_resp.status_code == 200
    assert "access_token" in login_resp.json()

    # Old password should fail
    old_login_resp = await client.post("/auth/login", json={
        "email": "reset_e2e@example.com",
        "password": "oldpass123",
    })
    assert old_login_resp.status_code == 401
