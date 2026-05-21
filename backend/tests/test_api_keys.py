"""Tests for the API keys router."""
import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_create_api_key(client: AsyncClient, get_auth_token: str):
    """Owner can create an API key."""
    headers = {"Authorization": f"Bearer {get_auth_token}"}

    response = await client.post(
        "/api/keys",
        json={"name": "Test MCP Key", "scope": "mcp", "permissions": "read,write"},
        headers=headers,
    )
    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "Test MCP Key"
    assert data["scope"] == "mcp"
    assert data["permissions"] == "read,write"
    assert data["full_key"].startswith("riq_")
    assert len(data["key_prefix"]) == 8


@pytest.mark.asyncio
async def test_create_api_key_invalid_scope(client: AsyncClient, get_auth_token: str):
    """Invalid scope returns 400."""
    headers = {"Authorization": f"Bearer {get_auth_token}"}

    response = await client.post(
        "/api/keys",
        json={"name": "Bad Key", "scope": "invalid", "permissions": "read"},
        headers=headers,
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_create_api_key_invalid_permissions(client: AsyncClient, get_auth_token: str):
    """Invalid permissions returns 400."""
    headers = {"Authorization": f"Bearer {get_auth_token}"}

    response = await client.post(
        "/api/keys",
        json={"name": "Bad Key", "scope": "cli", "permissions": "superadmin"},
        headers=headers,
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_list_api_keys(client: AsyncClient, get_auth_token: str):
    """Owner can list API keys."""
    headers = {"Authorization": f"Bearer {get_auth_token}"}

    # Create a key first
    await client.post(
        "/api/keys",
        json={"name": "List Test Key", "scope": "agent", "permissions": "read"},
        headers=headers,
    )

    response = await client.get("/api/keys", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) >= 1
    assert data[0]["name"] == "List Test Key"


@pytest.mark.asyncio
async def test_get_api_key_by_id(client: AsyncClient, get_auth_token: str):
    """Owner can get a specific API key."""
    headers = {"Authorization": f"Bearer {get_auth_token}"}

    create_resp = await client.post(
        "/api/keys",
        json={"name": "Get Test Key", "scope": "cli", "permissions": "read"},
        headers=headers,
    )
    key_id = create_resp.json()["id"]

    response = await client.get(f"/api/keys/{key_id}", headers=headers)
    assert response.status_code == 200
    assert response.json()["name"] == "Get Test Key"


@pytest.mark.asyncio
async def test_get_api_key_not_found(client: AsyncClient, get_auth_token: str):
    """Getting non-existent key returns 404."""
    headers = {"Authorization": f"Bearer {get_auth_token}"}

    response = await client.get("/api/keys/99999", headers=headers)
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_update_api_key(client: AsyncClient, get_auth_token: str):
    """Owner can update an API key."""
    headers = {"Authorization": f"Bearer {get_auth_token}"}

    create_resp = await client.post(
        "/api/keys",
        json={"name": "Update Me", "scope": "agent", "permissions": "read"},
        headers=headers,
    )
    key_id = create_resp.json()["id"]

    response = await client.patch(
        f"/api/keys/{key_id}",
        json={"name": "Updated Name", "permissions": "read,write"},
        headers=headers,
    )
    assert response.status_code == 200
    assert response.json()["name"] == "Updated Name"
    assert response.json()["permissions"] == "read,write"


@pytest.mark.asyncio
async def test_revoke_api_key(client: AsyncClient, get_auth_token: str):
    """Owner can revoke (deactivate) an API key."""
    headers = {"Authorization": f"Bearer {get_auth_token}"}

    create_resp = await client.post(
        "/api/keys",
        json={"name": "Revoke Me", "scope": "skill", "permissions": "read"},
        headers=headers,
    )
    key_id = create_resp.json()["id"]

    response = await client.delete(f"/api/keys/{key_id}", headers=headers)
    assert response.status_code == 200
    assert response.json()["status"] == "revoked"

    # Verify it's inactive
    get_resp = await client.get(f"/api/keys/{key_id}", headers=headers)
    assert get_resp.json()["is_active"] is False


@pytest.mark.asyncio
async def test_create_key_with_expiry(client: AsyncClient, get_auth_token: str):
    """Key with expiry date is created correctly."""
    headers = {"Authorization": f"Bearer {get_auth_token}"}

    response = await client.post(
        "/api/keys",
        json={"name": "Expiring Key", "scope": "agent", "permissions": "read", "expires_in_days": 30},
        headers=headers,
    )
    assert response.status_code == 201
    data = response.json()
    assert data["expires_at"] is not None


@pytest.mark.asyncio
async def test_non_owner_cannot_create_key(client: AsyncClient, get_auth_token: str, db_session):
    """Non-owner cannot create API keys."""
    from app.models import User
    from app.services.auth import hash_password, create_access_token
    from sqlalchemy import select

    user_result = await db_session.execute(select(User).where(User.email == "testuser@example.com"))
    owner = user_result.scalar_one()

    member = User(
        email="nokeys@example.com",
        password_hash=hash_password("password123"),
        full_name="No Keys",
        tenant_id=owner.tenant_id,
        is_owner=False,
    )
    db_session.add(member)
    await db_session.commit()
    await db_session.refresh(member)

    me_resp = await client.get("/auth/me", headers={"Authorization": f"Bearer {get_auth_token}"})
    tenant_slug = me_resp.json()["tenant_slug"]

    member_token = create_access_token(data={"user_id": member.id, "tenant_slug": tenant_slug})
    member_headers = {"Authorization": f"Bearer {member_token}"}

    response = await client.post(
        "/api/keys",
        json={"name": "Should Fail", "scope": "agent", "permissions": "read"},
        headers=member_headers,
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_exchange_key_for_token(client: AsyncClient, get_auth_token: str):
    """API key can be exchanged for a short-lived JWT."""
    headers = {"Authorization": f"Bearer {get_auth_token}"}

    # Create a key
    create_resp = await client.post(
        "/api/keys",
        json={"name": "Exchange Key", "scope": "mcp", "permissions": "read"},
        headers=headers,
    )
    full_key = create_resp.json()["full_key"]

    # Exchange it
    response = await client.post(
        "/api/keys/exchange",
        headers={"X-API-Key": full_key},
    )
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"
    assert data["session_type"] == "mcp"
    assert data["expires_in"] == 1800
