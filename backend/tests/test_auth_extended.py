"""Extended auth tests covering invite, team, roles, password reset, bot token, profile updates."""
import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_invite_user(client: AsyncClient, get_auth_token: str):
    """Owner can invite a team member."""
    headers = {"Authorization": f"Bearer {get_auth_token}"}

    response = await client.post(
        "/auth/invite",
        json={"email": "invited@example.com"},
        headers=headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert "temp_password" in data
    assert len(data["temp_password"]) == 12


@pytest.mark.asyncio
async def test_invite_duplicate_email(client: AsyncClient, get_auth_token: str):
    """Inviting an existing email returns 409."""
    headers = {"Authorization": f"Bearer {get_auth_token}"}

    await client.post("/auth/invite", json={"email": "dup_invite@example.com"}, headers=headers)
    response = await client.post("/auth/invite", json={"email": "dup_invite@example.com"}, headers=headers)
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_invite_non_owner_forbidden(client: AsyncClient, get_auth_token: str, db_session):
    """Non-owner cannot invite."""
    from app.models import User
    from app.services.auth import hash_password, create_access_token
    from sqlalchemy import select

    user_result = await db_session.execute(select(User).where(User.email == "testuser@example.com"))
    owner = user_result.scalar_one()

    member = User(
        email="noinvite@example.com",
        password_hash=hash_password("password123"),
        full_name="No Invite",
        tenant_id=owner.tenant_id,
        is_owner=False,
    )
    db_session.add(member)
    await db_session.commit()

    me_resp = await client.get("/auth/me", headers={"Authorization": f"Bearer {get_auth_token}"})
    tenant_slug = me_resp.json()["tenant_slug"]
    member_token = create_access_token(data={"user_id": member.id, "tenant_slug": tenant_slug})

    response = await client.post(
        "/auth/invite",
        json={"email": "someone@example.com"},
        headers={"Authorization": f"Bearer {member_token}"},
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_list_team(client: AsyncClient, get_auth_token: str):
    """Owner can list team members."""
    headers = {"Authorization": f"Bearer {get_auth_token}"}

    response = await client.get("/auth/team", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) >= 1
    assert data[0]["email"] == "testuser@example.com"


@pytest.mark.asyncio
async def test_set_user_role(client: AsyncClient, get_auth_token: str, db_session):
    """Owner can promote a team member."""
    headers = {"Authorization": f"Bearer {get_auth_token}"}

    # Invite a member first
    invite_resp = await client.post(
        "/auth/invite",
        json={"email": "promote@example.com"},
        headers=headers,
    )
    assert invite_resp.status_code == 200

    # Get team to find the member's ID
    team_resp = await client.get("/auth/team", headers=headers)
    team = team_resp.json()
    member = next(m for m in team if m["email"] == "promote@example.com")

    # Promote
    response = await client.patch(
        f"/auth/team/{member['id']}/role",
        json={"is_owner": True},
        headers=headers,
    )
    assert response.status_code == 200
    assert response.json()["is_owner"] is True


@pytest.mark.asyncio
async def test_cannot_change_own_role(client: AsyncClient, get_auth_token: str):
    """Owner cannot change their own role."""
    headers = {"Authorization": f"Bearer {get_auth_token}"}

    me_resp = await client.get("/auth/me", headers=headers)
    my_id = me_resp.json()["id"]

    response = await client.patch(
        f"/auth/team/{my_id}/role",
        json={"is_owner": False},
        headers=headers,
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_update_profile(client: AsyncClient, get_auth_token: str):
    """User can update their profile."""
    headers = {"Authorization": f"Bearer {get_auth_token}"}

    response = await client.patch(
        "/auth/me",
        json={"full_name": "Updated Name"},
        headers=headers,
    )
    assert response.status_code == 200
    assert response.json()["full_name"] == "Updated Name"


@pytest.mark.asyncio
async def test_get_tenant(client: AsyncClient, get_auth_token: str):
    """User can get their tenant details."""
    headers = {"Authorization": f"Bearer {get_auth_token}"}

    response = await client.get("/auth/tenant", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert "slug" in data
    assert "name" in data
    assert data["is_active"] is True


@pytest.mark.asyncio
async def test_update_tenant(client: AsyncClient, get_auth_token: str):
    """Owner can update tenant settings."""
    headers = {"Authorization": f"Bearer {get_auth_token}"}

    response = await client.patch(
        "/auth/tenant",
        json={"name": "Updated Company Name"},
        headers=headers,
    )
    assert response.status_code == 200
    assert response.json()["name"] == "Updated Company Name"


@pytest.mark.asyncio
async def test_forgot_password(client: AsyncClient, get_auth_token: str):
    """Forgot password returns a reset token."""
    # Register a user first (already done via get_auth_token fixture)
    response = await client.post(
        "/auth/forgot-password",
        json={"email": "testuser@example.com"},
    )
    assert response.status_code == 200
    data = response.json()
    assert "reset_token" in data


@pytest.mark.asyncio
async def test_forgot_password_nonexistent_email(client: AsyncClient):
    """Forgot password with non-existent email still returns success (no enumeration)."""
    response = await client.post(
        "/auth/forgot-password",
        json={"email": "nobody@example.com"},
    )
    assert response.status_code == 200
    # Should NOT have reset_token for non-existent user
    data = response.json()
    assert "message" in data


@pytest.mark.asyncio
async def test_reset_password(client: AsyncClient, get_auth_token: str):
    """Password can be reset with a valid token."""
    # Get reset token
    forgot_resp = await client.post(
        "/auth/forgot-password",
        json={"email": "testuser@example.com"},
    )
    reset_token = forgot_resp.json()["reset_token"]

    # Reset password
    response = await client.post(
        "/auth/reset-password",
        json={"token": reset_token, "new_password": "newpassword123"},
    )
    assert response.status_code == 200
    assert "successfully" in response.json()["message"].lower()

    # Login with new password
    login_resp = await client.post(
        "/auth/login",
        json={"email": "testuser@example.com", "password": "newpassword123"},
    )
    assert login_resp.status_code == 200


@pytest.mark.asyncio
async def test_reset_password_invalid_token(client: AsyncClient):
    """Invalid reset token returns 400."""
    response = await client.post(
        "/auth/reset-password",
        json={"token": "invalid-token", "new_password": "newpassword123"},
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_reset_password_too_short(client: AsyncClient, get_auth_token: str):
    """Short password returns 400."""
    forgot_resp = await client.post(
        "/auth/forgot-password",
        json={"email": "testuser@example.com"},
    )
    reset_token = forgot_resp.json()["reset_token"]

    response = await client.post(
        "/auth/reset-password",
        json={"token": reset_token, "new_password": "short"},
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_bot_token(client: AsyncClient, get_auth_token: str, monkeypatch):
    """Bot can get a token for a registered user."""
    monkeypatch.setenv("BOT_API_KEY", "test-bot-key")
    from app.config import get_settings
    get_settings.cache_clear()

    response = await client.post(
        "/auth/bot/token",
        json={"email": "testuser@example.com"},
        headers={"X-Bot-Token": "test-bot-key"},
    )
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"

    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_bot_token_invalid_key(client: AsyncClient, get_auth_token: str, monkeypatch):
    """Bot with wrong key is rejected."""
    monkeypatch.setenv("BOT_API_KEY", "test-bot-key")
    from app.config import get_settings
    get_settings.cache_clear()

    response = await client.post(
        "/auth/bot/token",
        json={"email": "testuser@example.com"},
        headers={"X-Bot-Token": "wrong-key"},
    )
    assert response.status_code == 401

    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_bot_token_user_not_found(client: AsyncClient, monkeypatch):
    """Bot token for non-existent user returns 404."""
    monkeypatch.setenv("BOT_API_KEY", "test-bot-key")
    from app.config import get_settings
    get_settings.cache_clear()

    response = await client.post(
        "/auth/bot/token",
        json={"email": "nobody@example.com"},
        headers={"X-Bot-Token": "test-bot-key"},
    )
    assert response.status_code == 404

    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_login_inactive_user(client: AsyncClient, db_session):
    """Inactive user cannot login."""
    from app.models import User, Tenant
    from app.services.auth import hash_password

    tenant = Tenant(name="Inactive Co", slug="inactive-co")
    db_session.add(tenant)
    await db_session.flush()

    user = User(
        email="inactive@example.com",
        password_hash=hash_password("password123"),
        full_name="Inactive User",
        tenant_id=tenant.id,
        is_owner=True,
        is_active=False,
    )
    db_session.add(user)
    await db_session.commit()

    response = await client.post(
        "/auth/login",
        json={"email": "inactive@example.com", "password": "password123"},
    )
    assert response.status_code == 403
