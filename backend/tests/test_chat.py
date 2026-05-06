import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_empty_kb_message(client: AsyncClient, get_auth_token: str):
    """Test that asking a question when KB is empty returns a helpful empty KB message."""
    headers = {"Authorization": f"Bearer {get_auth_token}"}
    me_resp = await client.get("/auth/me", headers=headers)
    tenant_slug = me_resp.json()["tenant_slug"]

    payload = {"question": "What is the leave policy?"}
    response = await client.post(f"/{tenant_slug}/chat/ask", json=payload, headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert "knowledge base is currently empty" in data["answer"].lower()
    assert data["sources"] == []


@pytest.mark.asyncio
async def test_chat_with_docs(client: AsyncClient, get_auth_token: str):
    """Test asking a question after adding documents to the KB."""
    headers = {"Authorization": f"Bearer {get_auth_token}"}
    me_resp = await client.get("/auth/me", headers=headers)
    tenant_slug = me_resp.json()["tenant_slug"]

    # Add a document first
    doc_payload = {
        "title": "Leave Policy",
        "content": "Employees are entitled to 20 days of paid annual leave per year. Leave must be requested at least 5 days in advance and approved by the manager.",
    }
    await client.post(f"/{tenant_slug}/kb/", json=doc_payload, headers=headers)

    # Ask a related question
    payload = {"question": "How many days of leave do I get?"}
    response = await client.post(f"/{tenant_slug}/chat/ask", json=payload, headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data["answer"], str)
    assert len(data["answer"]) > 0
    # With a valid GROQ_API_KEY this would be an AI answer; without it returns a non-AI fallback
    assert isinstance(data["sources"], list)


@pytest.mark.asyncio
async def test_empty_question(client: AsyncClient, get_auth_token: str):
    """Test that sending an empty/whitespace-only question is handled gracefully."""
    headers = {"Authorization": f"Bearer {get_auth_token}"}
    me_resp = await client.get("/auth/me", headers=headers)
    tenant_slug = me_resp.json()["tenant_slug"]

    payload = {"question": "   "}
    response = await client.post(f"/{tenant_slug}/chat/ask", json=payload, headers=headers)
    # The endpoint processes the query; with no matching docs it returns the "couldn't find" message
    assert response.status_code == 200
    data = response.json()
    assert "answer" in data
    assert isinstance(data["sources"], list)
