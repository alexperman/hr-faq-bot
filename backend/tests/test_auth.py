import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_register(client: AsyncClient):
    """Test successful user registration."""
    payload = {
        "email": "newuser@example.com",
        "password": "securepassword123",
        "full_name": "New User",
        "company_name": "New Company",
    }
    response = await client.post("/auth/register", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"


@pytest.mark.asyncio
async def test_login(client: AsyncClient):
    """Test successful login after registration."""
    # Register first
    register_payload = {
        "email": "logintest@example.com",
        "password": "password123",
        "full_name": "Login Test",
        "company_name": "Login Test Company",
    }
    await client.post("/auth/register", json=register_payload)

    # Login
    login_payload = {
        "email": "logintest@example.com",
        "password": "password123",
    }
    response = await client.post("/auth/login", json=login_payload)
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"


@pytest.mark.asyncio
async def test_login_wrong_password(client: AsyncClient):
    """Test login with incorrect password fails."""
    # Register first
    register_payload = {
        "email": "wrongpw@example.com",
        "password": "correctpassword",
        "full_name": "Wrong PW Test",
        "company_name": "Wrong PW Company",
    }
    await client.post("/auth/register", json=register_payload)

    # Login with wrong password
    login_payload = {
        "email": "wrongpw@example.com",
        "password": "wrongpassword",
    }
    response = await client.post("/auth/login", json=login_payload)
    assert response.status_code == 401
    data = response.json()
    # Structured error format
    assert data["error"]["message"] == "Invalid email or password"


@pytest.mark.asyncio
async def test_register_duplicate_email(client: AsyncClient):
    """Test that registering with an existing email returns 409."""
    payload = {
        "email": "duplicate@example.com",
        "password": "password123",
        "full_name": "Duplicate Test",
        "company_name": "Duplicate Company First",
    }
    first_resp = await client.post("/auth/register", json=payload)
    assert first_resp.status_code == 200

    # Try to register again with same email and a unique company name
    payload2 = {
        "email": "duplicate@example.com",
        "password": "password123",
        "full_name": "Duplicate Test 2",
        "company_name": "Totally Different Unique Corp 999",
    }
    response = await client.post("/auth/register", json=payload2)
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_me_endpoint(client: AsyncClient):
    """Test /auth/me returns user info with valid token."""
    # Register and get token via fixture
    register_payload = {
        "email": "me@example.com",
        "password": "password123",
        "full_name": "Me Test",
        "company_name": "Me Company",
    }
    reg_response = await client.post("/auth/register", json=register_payload)
    token = reg_response.json()["access_token"]

    # Call /auth/me
    response = await client.get(
        "/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["email"] == "me@example.com"
    assert data["full_name"] == "Me Test"
    assert data["is_owner"] is True
    assert "tenant_slug" in data
