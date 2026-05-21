"""Extended chat tests covering history, search, rate limiting."""
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
async def test_chat_history(client: AsyncClient, get_auth_token: str):
    """Chat history returns messages after asking a question."""
    headers = {"Authorization": f"Bearer {get_auth_token}"}
    me_resp = await client.get("/auth/me", headers=headers)
    tenant_slug = me_resp.json()["tenant_slug"]

    # Add a doc
    doc_payload = {
        "title": "History Test Policy",
        "content": "Employees get 20 days of vacation per year. This is the standard policy for all full-time employees.",
    }
    await client.post(f"/{tenant_slug}/kb/", json=doc_payload, headers=headers)

    # Ask a question (mock groq)
    with patch("app.routers.chat.ask_groq", new_callable=AsyncMock) as mock_groq:
        mock_groq.return_value = "You get 20 days of vacation per year."
        await client.post(
            f"/{tenant_slug}/chat/ask",
            json={"question": "How many vacation days?"},
            headers=headers,
        )

    # Get history
    response = await client.get(f"/{tenant_slug}/chat/history", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) >= 2  # user message + ai response
    roles = [m["role"] for m in data]
    assert "user" in roles
    assert "ai" in roles


@pytest.mark.asyncio
async def test_chat_history_pagination(client: AsyncClient, get_auth_token: str):
    """Chat history supports limit and offset."""
    headers = {"Authorization": f"Bearer {get_auth_token}"}
    me_resp = await client.get("/auth/me", headers=headers)
    tenant_slug = me_resp.json()["tenant_slug"]

    response = await client.get(
        f"/{tenant_slug}/chat/history?limit=5&offset=0",
        headers=headers,
    )
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_chat_search(client: AsyncClient, get_auth_token: str):
    """Chat search finds messages by content."""
    headers = {"Authorization": f"Bearer {get_auth_token}"}
    me_resp = await client.get("/auth/me", headers=headers)
    tenant_slug = me_resp.json()["tenant_slug"]

    # Add a doc and ask a question
    doc_payload = {
        "title": "Search Test Policy",
        "content": "The company provides health insurance benefits to all employees including dental and vision coverage.",
    }
    await client.post(f"/{tenant_slug}/kb/", json=doc_payload, headers=headers)

    with patch("app.routers.chat.ask_groq", new_callable=AsyncMock) as mock_groq:
        mock_groq.return_value = "Health insurance includes dental and vision."
        await client.post(
            f"/{tenant_slug}/chat/ask",
            json={"question": "What health insurance do we have?"},
            headers=headers,
        )

    # Search
    response = await client.get(
        f"/{tenant_slug}/chat/search?q=health",
        headers=headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) >= 1


@pytest.mark.asyncio
async def test_chat_search_min_length(client: AsyncClient, get_auth_token: str):
    """Chat search requires minimum 2 characters."""
    headers = {"Authorization": f"Bearer {get_auth_token}"}
    me_resp = await client.get("/auth/me", headers=headers)
    tenant_slug = me_resp.json()["tenant_slug"]

    response = await client.get(
        f"/{tenant_slug}/chat/search?q=a",
        headers=headers,
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_chat_wrong_tenant(client: AsyncClient, get_auth_token: str):
    """Chat ask with wrong tenant returns 404."""
    headers = {"Authorization": f"Bearer {get_auth_token}"}

    response = await client.post(
        "/nonexistent-tenant/chat/ask",
        json={"question": "Test?"},
        headers=headers,
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_chat_rate_limit(client: AsyncClient, get_auth_token: str):
    """Rate limiting kicks in after too many requests."""
    headers = {"Authorization": f"Bearer {get_auth_token}"}
    me_resp = await client.get("/auth/me", headers=headers)
    tenant_slug = me_resp.json()["tenant_slug"]

    # Add a doc
    doc_payload = {
        "title": "Rate Limit Test",
        "content": "This is a test document for rate limiting purposes with enough content to pass validation.",
    }
    await client.post(f"/{tenant_slug}/kb/", json=doc_payload, headers=headers)

    # Send 21 requests (limit is 20/minute)
    with patch("app.routers.chat.ask_groq", new_callable=AsyncMock) as mock_groq:
        mock_groq.return_value = "Answer."
        last_status = 200
        for i in range(22):
            response = await client.post(
                f"/{tenant_slug}/chat/ask",
                json={"question": f"Question {i}?"},
                headers=headers,
            )
            last_status = response.status_code
            if last_status == 429:
                break

    assert last_status == 429


@pytest.mark.asyncio
async def test_chat_no_relevant_docs(client: AsyncClient, get_auth_token: str):
    """Chat with docs but no relevant match returns appropriate message."""
    headers = {"Authorization": f"Bearer {get_auth_token}"}
    me_resp = await client.get("/auth/me", headers=headers)
    tenant_slug = me_resp.json()["tenant_slug"]

    # Add a doc about something specific
    doc_payload = {
        "title": "Parking Policy",
        "content": "Employees can park in lot B. Visitors use lot A. Parking passes are issued by facilities management.",
    }
    await client.post(f"/{tenant_slug}/kb/", json=doc_payload, headers=headers)

    # Ask about something completely unrelated
    response = await client.post(
        f"/{tenant_slug}/chat/ask",
        json={"question": "xyzzy quantum entanglement protocol"},
        headers=headers,
    )
    assert response.status_code == 200
    data = response.json()
    # Either finds no relevant docs or returns an answer
    assert "answer" in data


@pytest.mark.asyncio
async def test_chat_follow_ups_parsed(client: AsyncClient, get_auth_token: str):
    """Follow-up questions are parsed from AI response."""
    headers = {"Authorization": f"Bearer {get_auth_token}"}
    me_resp = await client.get("/auth/me", headers=headers)
    tenant_slug = me_resp.json()["tenant_slug"]

    doc_payload = {
        "title": "Follow Up Test",
        "content": "Employees get 15 PTO days per year. Unused days roll over up to 5 days maximum.",
    }
    await client.post(f"/{tenant_slug}/kb/", json=doc_payload, headers=headers)

    with patch("app.routers.chat.ask_groq", new_callable=AsyncMock) as mock_groq:
        mock_groq.return_value = "You get 15 PTO days.\nFOLLOW_UP:Can I roll over unused days?|How do I request PTO?"
        response = await client.post(
            f"/{tenant_slug}/chat/ask",
            json={"question": "How many PTO days?"},
            headers=headers,
        )

    assert response.status_code == 200
    data = response.json()
    assert len(data["follow_ups"]) == 2
    assert "roll over" in data["follow_ups"][0].lower()
