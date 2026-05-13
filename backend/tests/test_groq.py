"""Tests for the Groq AI service and chat integration."""
import pytest
from unittest.mock import patch, AsyncMock, MagicMock
import httpx

from app.services.groq import ask_groq, _truncate_context


# ─── Unit tests for context truncation ────────────────────────────────────────

class TestTruncateContext:
    def test_empty_docs(self):
        result = _truncate_context([])
        assert result == "No relevant context provided."

    def test_single_short_doc(self):
        result = _truncate_context(["Hello world"])
        assert result == "Hello world"

    def test_multiple_docs_within_limit(self):
        docs = ["Doc one content", "Doc two content"]
        result = _truncate_context(docs, max_chars=1000)
        assert "Doc one content" in result
        assert "Doc two content" in result
        assert "---" in result  # separator

    def test_truncates_when_exceeding_limit(self):
        docs = ["A" * 500, "B" * 500, "C" * 500]
        result = _truncate_context(docs, max_chars=800)
        assert "A" * 500 in result
        # Second doc should be truncated
        assert "[... truncated]" in result
        # Third doc should not appear
        assert "C" * 500 not in result

    def test_skips_tiny_remainder(self):
        docs = ["A" * 990, "B" * 500]
        result = _truncate_context(docs, max_chars=1000)
        # Only 10 chars remaining, less than 200 threshold, so second doc is skipped
        assert "B" not in result
        assert "[... truncated]" not in result

    def test_respects_max_chars_default(self):
        # Default is 60000
        big_doc = "X" * 100000
        result = _truncate_context([big_doc])
        assert len(result) <= 60100  # 60000 + "[... truncated]" + small overhead


# ─── Unit tests for ask_groq ──────────────────────────────────────────────────

@pytest.mark.asyncio
class TestAskGroq:
    @patch("app.services.groq.get_settings")
    async def test_returns_error_when_no_api_key(self, mock_settings):
        mock_settings.return_value = MagicMock(GROQ_API_KEY="")
        result = await ask_groq("What is PTO?", ["Some context"])
        assert "not configured" in result.lower() or "GROQ_API_KEY" in result

    @patch("app.services.groq.get_settings")
    @patch("app.services.groq.httpx.AsyncClient")
    async def test_successful_response(self, mock_client_cls, mock_settings):
        mock_settings.return_value = MagicMock(GROQ_API_KEY="gsk_test_key_123")

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "You get 15 PTO days per year."}}]
        }

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        result = await ask_groq("How many PTO days?", ["PTO policy: 15 days per year"])
        assert "15" in result
        assert "PTO" in result

    @patch("app.services.groq.get_settings")
    @patch("app.services.groq.httpx.AsyncClient")
    async def test_handles_401_unauthorized(self, mock_client_cls, mock_settings):
        mock_settings.return_value = MagicMock(GROQ_API_KEY="gsk_invalid_key")

        mock_response = MagicMock()
        mock_response.status_code = 401
        error = httpx.HTTPStatusError("Unauthorized", request=MagicMock(), response=mock_response)

        mock_client = AsyncMock()
        mock_client.post.side_effect = error
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        result = await ask_groq("Question?", ["context"])
        assert "401" in result

    @patch("app.services.groq.get_settings")
    @patch("app.services.groq.httpx.AsyncClient")
    async def test_handles_413_payload_too_large(self, mock_client_cls, mock_settings):
        mock_settings.return_value = MagicMock(GROQ_API_KEY="gsk_test_key")

        mock_response = MagicMock()
        mock_response.status_code = 413
        error = httpx.HTTPStatusError("Payload too large", request=MagicMock(), response=mock_response)

        mock_client = AsyncMock()
        mock_client.post.side_effect = error
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        result = await ask_groq("Question?", ["context"])
        assert "413" in result

    @patch("app.services.groq.get_settings")
    @patch("app.services.groq.httpx.AsyncClient")
    async def test_handles_network_error(self, mock_client_cls, mock_settings):
        mock_settings.return_value = MagicMock(GROQ_API_KEY="gsk_test_key")

        mock_client = AsyncMock()
        mock_client.post.side_effect = httpx.ConnectError("Connection refused")
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        result = await ask_groq("Question?", ["context"])
        assert "failed" in result.lower()

    @patch("app.services.groq.get_settings")
    @patch("app.services.groq.httpx.AsyncClient")
    async def test_handles_timeout(self, mock_client_cls, mock_settings):
        mock_settings.return_value = MagicMock(GROQ_API_KEY="gsk_test_key")

        mock_client = AsyncMock()
        mock_client.post.side_effect = httpx.ReadTimeout("Timeout")
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        result = await ask_groq("Question?", ["context"])
        assert "failed" in result.lower()

    @patch("app.services.groq.get_settings")
    @patch("app.services.groq.httpx.AsyncClient")
    async def test_context_is_truncated_before_sending(self, mock_client_cls, mock_settings):
        mock_settings.return_value = MagicMock(GROQ_API_KEY="gsk_test_key")

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "Answer"}}]
        }

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        # Send a huge context
        big_docs = ["X" * 100000]
        await ask_groq("Question?", big_docs)

        # Verify the payload sent was truncated
        call_args = mock_client.post.call_args
        payload = call_args.kwargs.get("json") or call_args[1].get("json")
        user_content = payload["messages"][1]["content"]
        # Should be well under 100k (truncated to ~60k)
        assert len(user_content) < 65000

    @patch("app.services.groq.get_settings")
    @patch("app.services.groq.httpx.AsyncClient")
    async def test_empty_context_still_works(self, mock_client_cls, mock_settings):
        mock_settings.return_value = MagicMock(GROQ_API_KEY="gsk_test_key")

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "I don't have that information."}}]
        }

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        result = await ask_groq("Random question?", [])
        assert "don't have" in result.lower() or "information" in result.lower()
