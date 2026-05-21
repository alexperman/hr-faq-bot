"""Tests for the escalations router."""
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
async def test_list_escalations_empty(client: AsyncClient, get_auth_token: str):
    """List escalations returns empty list when none exist."""
    headers = {"Authorization": f"Bearer {get_auth_token}"}
    me_resp = await client.get("/auth/me", headers=headers)
    tenant_slug = me_resp.json()["tenant_slug"]

    response = await client.get(f"/{tenant_slug}/escalations/", headers=headers)
    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.asyncio
async def test_list_escalations_wrong_tenant(client: AsyncClient, get_auth_token: str):
    """Access denied for wrong tenant."""
    headers = {"Authorization": f"Bearer {get_auth_token}"}
    response = await client.get("/nonexistent-tenant/escalations/", headers=headers)
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_list_escalations_after_chat_escalation(client: AsyncClient, get_auth_token: str):
    """Escalation created via chat shows up in list."""
    headers = {"Authorization": f"Bearer {get_auth_token}"}
    me_resp = await client.get("/auth/me", headers=headers)
    tenant_slug = me_resp.json()["tenant_slug"]

    # Add a doc so chat works
    doc_payload = {
        "title": "Test Policy",
        "content": "This is a test policy document with enough content to pass validation requirements for the knowledge base system.",
    }
    await client.post(f"/{tenant_slug}/kb/", json=doc_payload, headers=headers)

    # Ask a question that triggers escalation (mock groq to return "I don't know")
    with patch("app.routers.chat.ask_groq", new_callable=AsyncMock) as mock_groq:
        mock_groq.return_value = "I don't know the answer to this question based on the available information."
        response = await client.post(
            f"/{tenant_slug}/chat/ask",
            json={"question": "What is the quantum physics policy?"},
            headers=headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["escalated"] is True
        assert data["escalation_id"] is not None

    # Now list escalations
    response = await client.get(f"/{tenant_slug}/escalations/", headers=headers)
    assert response.status_code == 200
    escalations = response.json()
    assert len(escalations) >= 1
    assert escalations[0]["question"] == "What is the quantum physics policy?"
    assert escalations[0]["status"] == "pending"


@pytest.mark.asyncio
async def test_reply_to_escalation(client: AsyncClient, get_auth_token: str, db_session):
    """Admin can reply to an escalation."""
    headers = {"Authorization": f"Bearer {get_auth_token}"}
    me_resp = await client.get("/auth/me", headers=headers)
    tenant_slug = me_resp.json()["tenant_slug"]

    # Create an escalation via the DB directly
    from app.models import Escalation, User, Tenant
    from sqlalchemy import select

    user_result = await db_session.execute(select(User).where(User.email == "testuser@example.com"))
    user = user_result.scalar_one()
    tenant_result = await db_session.execute(select(Tenant).where(Tenant.id == user.tenant_id))
    tenant = tenant_result.scalar_one()

    esc = Escalation(
        tenant_id=tenant.id,
        user_id=user.id,
        question="What is the dress code?",
        ai_partial_answer="I could not find this information.",
        status="pending",
    )
    db_session.add(esc)
    await db_session.commit()
    await db_session.refresh(esc)

    # Reply
    response = await client.post(
        f"/{tenant_slug}/escalations/{esc.id}/reply",
        json={"reply": "Business casual is the standard dress code."},
        headers=headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["admin_reply"] == "Business casual is the standard dress code."
    assert data["status"] == "replied"


@pytest.mark.asyncio
async def test_reply_non_owner_forbidden(client: AsyncClient, get_auth_token: str, db_session):
    """Non-owner cannot reply to escalations."""
    headers = {"Authorization": f"Bearer {get_auth_token}"}
    me_resp = await client.get("/auth/me", headers=headers)
    tenant_slug = me_resp.json()["tenant_slug"]

    # Create a non-owner user
    from app.models import User, Tenant, Escalation
    from app.services.auth import hash_password, create_access_token
    from sqlalchemy import select

    user_result = await db_session.execute(select(User).where(User.email == "testuser@example.com"))
    owner = user_result.scalar_one()

    member = User(
        email="member@example.com",
        password_hash=hash_password("password123"),
        full_name="Team Member",
        tenant_id=owner.tenant_id,
        is_owner=False,
    )
    db_session.add(member)
    await db_session.flush()

    esc = Escalation(
        tenant_id=owner.tenant_id,
        user_id=member.id,
        question="Test question?",
        status="pending",
    )
    db_session.add(esc)
    await db_session.commit()
    await db_session.refresh(esc)

    # Get token for member
    member_token = create_access_token(data={"user_id": member.id, "tenant_slug": tenant_slug})
    member_headers = {"Authorization": f"Bearer {member_token}"}

    response = await client.post(
        f"/{tenant_slug}/escalations/{esc.id}/reply",
        json={"reply": "Should not work"},
        headers=member_headers,
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_mark_as_read(client: AsyncClient, get_auth_token: str, db_session):
    """User can mark an escalation reply as read."""
    headers = {"Authorization": f"Bearer {get_auth_token}"}
    me_resp = await client.get("/auth/me", headers=headers)
    tenant_slug = me_resp.json()["tenant_slug"]

    from app.models import Escalation, User, Tenant
    from sqlalchemy import select
    from datetime import datetime, timezone

    user_result = await db_session.execute(select(User).where(User.email == "testuser@example.com"))
    user = user_result.scalar_one()

    esc = Escalation(
        tenant_id=user.tenant_id,
        user_id=user.id,
        question="Test read?",
        admin_reply="Here is the answer.",
        status="replied",
        replied_by=user.id,
        replied_at=datetime.now(timezone.utc),
        read_by_user=False,
    )
    db_session.add(esc)
    await db_session.commit()
    await db_session.refresh(esc)

    response = await client.post(
        f"/{tenant_slug}/escalations/{esc.id}/read",
        headers=headers,
    )
    assert response.status_code == 200
    assert response.json()["status"] == "read"


@pytest.mark.asyncio
async def test_mark_all_read(client: AsyncClient, get_auth_token: str, db_session):
    """User can mark all replied escalations as read."""
    headers = {"Authorization": f"Bearer {get_auth_token}"}
    me_resp = await client.get("/auth/me", headers=headers)
    tenant_slug = me_resp.json()["tenant_slug"]

    from app.models import Escalation, User
    from sqlalchemy import select
    from datetime import datetime, timezone

    user_result = await db_session.execute(select(User).where(User.email == "testuser@example.com"))
    user = user_result.scalar_one()

    for i in range(3):
        esc = Escalation(
            tenant_id=user.tenant_id,
            user_id=user.id,
            question=f"Question {i}?",
            admin_reply=f"Answer {i}.",
            status="replied",
            replied_by=user.id,
            replied_at=datetime.now(timezone.utc),
            read_by_user=False,
        )
        db_session.add(esc)
    await db_session.commit()

    response = await client.post(f"/{tenant_slug}/escalations/read-all", headers=headers)
    assert response.status_code == 200
    assert response.json()["marked"] == 3


@pytest.mark.asyncio
async def test_my_replies(client: AsyncClient, get_auth_token: str, db_session):
    """User can get their replied escalations."""
    headers = {"Authorization": f"Bearer {get_auth_token}"}
    me_resp = await client.get("/auth/me", headers=headers)
    tenant_slug = me_resp.json()["tenant_slug"]

    from app.models import Escalation, User
    from sqlalchemy import select
    from datetime import datetime, timezone

    user_result = await db_session.execute(select(User).where(User.email == "testuser@example.com"))
    user = user_result.scalar_one()

    esc = Escalation(
        tenant_id=user.tenant_id,
        user_id=user.id,
        question="My question?",
        admin_reply="Your answer.",
        status="replied",
        replied_by=user.id,
        replied_at=datetime.now(timezone.utc),
    )
    db_session.add(esc)
    await db_session.commit()

    response = await client.get(f"/{tenant_slug}/escalations/my-replies", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert len(data) >= 1
    assert data[0]["admin_reply"] == "Your answer."
