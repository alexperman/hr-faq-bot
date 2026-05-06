import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_add_doc(client: AsyncClient, get_auth_token: str):
    """Test adding a valid document to the knowledge base."""
    headers = {"Authorization": f"Bearer {get_auth_token}"}
    # Register + login to get tenant slug from me endpoint
    me_resp = await client.get("/auth/me", headers=headers)
    tenant_slug = me_resp.json()["tenant_slug"]

    payload = {
        "title": "HR Policy 2024",
        "content": "This is the HR policy document that outlines the rules and regulations for employees in the company. It covers working hours, leave policy, and code of conduct.",
        "source_url": "https://example.com/hr-policy",
    }
    response = await client.post(f"/{tenant_slug}/kb/", json=payload, headers=headers)
    assert response.status_code == 201
    data = response.json()
    assert data["title"] == "HR Policy 2024"
    assert data["char_count"] == len(payload["content"])
    assert data["source_url"] == "https://example.com/hr-policy"


@pytest.mark.asyncio
async def test_add_doc_too_short(client: AsyncClient, get_auth_token: str):
    """Test that adding a document with content under 50 characters fails."""
    headers = {"Authorization": f"Bearer {get_auth_token}"}
    me_resp = await client.get("/auth/me", headers=headers)
    tenant_slug = me_resp.json()["tenant_slug"]

    payload = {
        "title": "Too Short Doc",
        "content": "This is too short.",  # less than 50 chars
    }
    response = await client.post(f"/{tenant_slug}/kb/", json=payload, headers=headers)
    assert response.status_code == 422  # Validation error from pydantic


@pytest.mark.asyncio
async def test_list_docs(client: AsyncClient, get_auth_token: str):
    """Test listing documents returns the created docs."""
    headers = {"Authorization": f"Bearer {get_auth_token}"}
    me_resp = await client.get("/auth/me", headers=headers)
    tenant_slug = me_resp.json()["tenant_slug"]

    # Add a document first
    doc_payload = {
        "title": "Employee Handbook",
        "content": "This is the employee handbook that contains all the information about company policies, benefits, and procedures for all employees.",
    }
    await client.post(f"/{tenant_slug}/kb/", json=doc_payload, headers=headers)

    # List documents
    response = await client.get(f"/{tenant_slug}/kb/", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) >= 1
    assert data[0]["title"] == "Employee Handbook"


@pytest.mark.asyncio
async def test_delete_doc(client: AsyncClient, get_auth_token: str):
    """Test deleting an existing document."""
    headers = {"Authorization": f"Bearer {get_auth_token}"}
    me_resp = await client.get("/auth/me", headers=headers)
    tenant_slug = me_resp.json()["tenant_slug"]

    # Add a document
    doc_payload = {
        "title": "To Be Deleted",
        "content": "This document will be deleted from the knowledge base after creation for testing purposes.",
    }
    create_resp = await client.post(f"/{tenant_slug}/kb/", json=doc_payload, headers=headers)
    doc_id = create_resp.json()["id"]

    # Delete it
    delete_resp = await client.delete(f"/{tenant_slug}/kb/{doc_id}", headers=headers)
    assert delete_resp.status_code == 204

    # Verify it's gone
    list_resp = await client.get(f"/{tenant_slug}/kb/", headers=headers)
    remaining = list_resp.json()
    assert all(d["id"] != doc_id for d in remaining)
