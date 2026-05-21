"""Extended KB tests covering upload, import-url, get single doc, access control."""
import pytest
from httpx import AsyncClient
from unittest.mock import patch, AsyncMock, MagicMock
import io


@pytest.mark.asyncio
async def test_get_single_document(client: AsyncClient, get_auth_token: str):
    """Get a single document by ID."""
    headers = {"Authorization": f"Bearer {get_auth_token}"}
    me_resp = await client.get("/auth/me", headers=headers)
    tenant_slug = me_resp.json()["tenant_slug"]

    # Create a doc
    doc_payload = {
        "title": "Single Doc Test",
        "content": "This is a test document with enough content to pass the minimum character validation requirement.",
    }
    create_resp = await client.post(f"/{tenant_slug}/kb/", json=doc_payload, headers=headers)
    doc_id = create_resp.json()["id"]

    # Get it
    response = await client.get(f"/{tenant_slug}/kb/{doc_id}", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert data["title"] == "Single Doc Test"
    assert data["id"] == doc_id


@pytest.mark.asyncio
async def test_get_document_not_found(client: AsyncClient, get_auth_token: str):
    """Getting non-existent document returns 404."""
    headers = {"Authorization": f"Bearer {get_auth_token}"}
    me_resp = await client.get("/auth/me", headers=headers)
    tenant_slug = me_resp.json()["tenant_slug"]

    response = await client.get(f"/{tenant_slug}/kb/99999", headers=headers)
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_upload_txt_file(client: AsyncClient, get_auth_token: str):
    """Upload a .txt file to the KB."""
    headers = {"Authorization": f"Bearer {get_auth_token}"}
    me_resp = await client.get("/auth/me", headers=headers)
    tenant_slug = me_resp.json()["tenant_slug"]

    content = "This is a text file with enough content to pass the minimum character validation for the knowledge base system."
    files = {"file": ("test.txt", io.BytesIO(content.encode()), "text/plain")}
    data = {"title": "Uploaded TXT"}

    response = await client.post(
        f"/{tenant_slug}/kb/upload",
        files=files,
        data=data,
        headers=headers,
    )
    assert response.status_code == 201
    resp_data = response.json()
    assert resp_data["title"] == "Uploaded TXT"
    assert resp_data["char_count"] >= 50


@pytest.mark.asyncio
async def test_upload_file_too_short(client: AsyncClient, get_auth_token: str):
    """Upload with too little content returns 400."""
    headers = {"Authorization": f"Bearer {get_auth_token}"}
    me_resp = await client.get("/auth/me", headers=headers)
    tenant_slug = me_resp.json()["tenant_slug"]

    content = "Short."
    files = {"file": ("short.txt", io.BytesIO(content.encode()), "text/plain")}
    data = {"title": "Too Short"}

    response = await client.post(
        f"/{tenant_slug}/kb/upload",
        files=files,
        data=data,
        headers=headers,
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_upload_md_file(client: AsyncClient, get_auth_token: str):
    """Upload a .md file to the KB."""
    headers = {"Authorization": f"Bearer {get_auth_token}"}
    me_resp = await client.get("/auth/me", headers=headers)
    tenant_slug = me_resp.json()["tenant_slug"]

    content = "# HR Policy\n\nThis is a markdown document with enough content to pass the minimum character validation for the knowledge base."
    files = {"file": ("policy.md", io.BytesIO(content.encode()), "text/markdown")}
    data = {"title": "Markdown Policy"}

    response = await client.post(
        f"/{tenant_slug}/kb/upload",
        files=files,
        data=data,
        headers=headers,
    )
    assert response.status_code == 201


@pytest.mark.asyncio
async def test_import_url_success(client: AsyncClient, get_auth_token: str):
    """Import from URL creates a document."""
    headers = {"Authorization": f"Bearer {get_auth_token}"}
    me_resp = await client.get("/auth/me", headers=headers)
    tenant_slug = me_resp.json()["tenant_slug"]

    mock_response = MagicMock()
    mock_response.content = b"This is fetched content from a URL with enough text to pass the minimum character validation for the knowledge base system."
    mock_response.headers = {"content-type": "text/plain"}
    mock_response.raise_for_status = MagicMock()

    with patch("app.routers.kb.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        response = await client.post(
            f"/{tenant_slug}/kb/import-url",
            json={"title": "Imported Doc", "url": "https://example.com/policy.txt"},
            headers=headers,
        )

    assert response.status_code == 201
    data = response.json()
    assert data["title"] == "Imported Doc"
    assert data["source_url"] == "https://example.com/policy.txt"


@pytest.mark.asyncio
async def test_import_url_failure(client: AsyncClient, get_auth_token: str):
    """Import from unreachable URL returns 400."""
    headers = {"Authorization": f"Bearer {get_auth_token}"}
    me_resp = await client.get("/auth/me", headers=headers)
    tenant_slug = me_resp.json()["tenant_slug"]

    with patch("app.routers.kb.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.get.side_effect = Exception("Connection refused")
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        response = await client.post(
            f"/{tenant_slug}/kb/import-url",
            json={"title": "Failed Import", "url": "https://unreachable.example.com/doc"},
            headers=headers,
        )

    assert response.status_code == 400


@pytest.mark.asyncio
async def test_kb_non_owner_cannot_list(client: AsyncClient, get_auth_token: str, db_session):
    """Non-owner cannot list KB documents."""
    from app.models import User
    from app.services.auth import hash_password, create_access_token
    from sqlalchemy import select

    user_result = await db_session.execute(select(User).where(User.email == "testuser@example.com"))
    owner = user_result.scalar_one()

    member = User(
        email="nokb@example.com",
        password_hash=hash_password("password123"),
        full_name="No KB",
        tenant_id=owner.tenant_id,
        is_owner=False,
    )
    db_session.add(member)
    await db_session.commit()

    me_resp = await client.get("/auth/me", headers={"Authorization": f"Bearer {get_auth_token}"})
    tenant_slug = me_resp.json()["tenant_slug"]
    member_token = create_access_token(data={"user_id": member.id, "tenant_slug": tenant_slug})

    response = await client.get(
        f"/{tenant_slug}/kb/",
        headers={"Authorization": f"Bearer {member_token}"},
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_kb_wrong_tenant(client: AsyncClient, get_auth_token: str):
    """Cannot access KB of another tenant."""
    headers = {"Authorization": f"Bearer {get_auth_token}"}

    response = await client.get("/wrong-tenant/kb/", headers=headers)
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_delete_nonexistent_doc(client: AsyncClient, get_auth_token: str):
    """Deleting non-existent doc returns 404."""
    headers = {"Authorization": f"Bearer {get_auth_token}"}
    me_resp = await client.get("/auth/me", headers=headers)
    tenant_slug = me_resp.json()["tenant_slug"]

    response = await client.delete(f"/{tenant_slug}/kb/99999", headers=headers)
    assert response.status_code == 404
