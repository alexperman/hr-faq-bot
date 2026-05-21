"""Tests for hermes tools: api_client, env, paths, storage, telegram."""
import json
import os
import tempfile
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from hermes.tools.api_client import AdminClient, from_env
from hermes.tools.env import load_env
from hermes.tools.paths import hermes_root, memory_root
from hermes.tools.storage import utc_now_iso, atomic_write_text, write_json
from hermes.tools.telegram import post_message


# ─── AdminClient Tests ────────────────────────────────────────────────────────

class TestAdminClient:
    def test_init(self):
        client = AdminClient(base_url="http://localhost:5000", api_key="test-key")
        assert client.base_url == "http://localhost:5000"
        assert client.api_key == "test-key"
        assert client.timeout_s == 20

    def test_headers(self):
        client = AdminClient(base_url="http://localhost:5000", api_key="my-key")
        headers = client._headers()
        assert headers == {"Authorization": "Bearer my-key"}

    @patch("hermes.tools.api_client.requests.get")
    def test_get_json_success(self, mock_get):
        mock_response = MagicMock()
        mock_response.json.return_value = {"status": "ok"}
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        client = AdminClient(base_url="http://localhost:5000", api_key="key")
        result = client.get_json("/health")

        assert result == {"status": "ok"}
        mock_get.assert_called_once_with(
            "http://localhost:5000/health",
            headers={"Authorization": "Bearer key"},
            timeout=20,
        )

    @patch("hermes.tools.api_client.requests.get")
    def test_get_json_strips_trailing_slash(self, mock_get):
        mock_response = MagicMock()
        mock_response.json.return_value = {}
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        client = AdminClient(base_url="http://localhost:5000/", api_key="key")
        client.get_json("/test")

        mock_get.assert_called_once_with(
            "http://localhost:5000/test",
            headers={"Authorization": "Bearer key"},
            timeout=20,
        )

    def test_from_env_success(self):
        with patch.dict(os.environ, {
            "REPLYIQ_ADMIN_API_URL": "http://test:8000",
            "REPLYIQ_ADMIN_API_KEY": "env-key",
        }):
            client = from_env()
            assert client.base_url == "http://test:8000"
            assert client.api_key == "env-key"

    def test_from_env_missing_raises(self):
        with patch.dict(os.environ, {"REPLYIQ_ADMIN_API_URL": "", "REPLYIQ_ADMIN_API_KEY": ""}, clear=False):
            # Remove the keys entirely
            env = os.environ.copy()
            env.pop("REPLYIQ_ADMIN_API_URL", None)
            env.pop("REPLYIQ_ADMIN_API_KEY", None)
            with patch.dict(os.environ, env, clear=True):
                with pytest.raises(RuntimeError, match="Missing"):
                    from_env()


# ─── Env Loader Tests ─────────────────────────────────────────────────────────

class TestEnvLoader:
    def test_load_env_from_file(self, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text("TEST_VAR=hello\nANOTHER=world\n")

        # Clear any existing value
        os.environ.pop("TEST_VAR", None)
        os.environ.pop("ANOTHER", None)

        load_env(str(env_file))

        assert os.environ.get("TEST_VAR") == "hello"
        assert os.environ.get("ANOTHER") == "world"

        # Cleanup
        del os.environ["TEST_VAR"]
        del os.environ["ANOTHER"]

    def test_load_env_skips_comments(self, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text("# This is a comment\nVALID_KEY=value\n")

        os.environ.pop("VALID_KEY", None)
        load_env(str(env_file))
        assert os.environ.get("VALID_KEY") == "value"
        del os.environ["VALID_KEY"]

    def test_load_env_strips_quotes(self, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text('QUOTED="hello world"\nSINGLE=\'single\'\n')

        os.environ.pop("QUOTED", None)
        os.environ.pop("SINGLE", None)
        load_env(str(env_file))
        assert os.environ.get("QUOTED") == "hello world"
        assert os.environ.get("SINGLE") == "single"
        del os.environ["QUOTED"]
        del os.environ["SINGLE"]

    def test_load_env_missing_file(self):
        """Missing file is a no-op."""
        load_env("/nonexistent/path/.env")
        # Should not raise

    def test_load_env_does_not_overwrite(self, tmp_path):
        """setdefault means existing env vars are not overwritten."""
        env_file = tmp_path / ".env"
        env_file.write_text("EXISTING=new_value\n")

        os.environ["EXISTING"] = "original"
        load_env(str(env_file))
        assert os.environ["EXISTING"] == "original"
        del os.environ["EXISTING"]


# ─── Paths Tests ──────────────────────────────────────────────────────────────

class TestPaths:
    def test_hermes_root(self):
        root = hermes_root()
        assert root.exists()
        assert root.name == "hermes"

    def test_memory_root(self):
        root = memory_root()
        assert root.parent.name == "hermes"
        assert root.name == "memory"


# ─── Storage Tests ────────────────────────────────────────────────────────────

class TestStorage:
    def test_utc_now_iso(self):
        result = utc_now_iso()
        assert "T" in result
        assert "+" in result or "Z" in result

    def test_atomic_write_text(self, tmp_path):
        target = tmp_path / "subdir" / "test.txt"
        atomic_write_text(target, "hello world")
        assert target.read_text() == "hello world"

    def test_write_json(self, tmp_path):
        target = tmp_path / "data.json"
        write_json(target, {"key": "value", "num": 42})
        data = json.loads(target.read_text())
        assert data["key"] == "value"
        assert data["num"] == 42

    def test_write_json_creates_dirs(self, tmp_path):
        target = tmp_path / "deep" / "nested" / "data.json"
        write_json(target, {"nested": True})
        assert target.exists()

    def test_write_json_dataclass(self, tmp_path):
        from dataclasses import dataclass

        @dataclass
        class Sample:
            name: str
            count: int

        target = tmp_path / "dc.json"
        write_json(target, Sample(name="test", count=5))
        data = json.loads(target.read_text())
        assert data["name"] == "test"
        assert data["count"] == 5


# ─── Telegram Tests ───────────────────────────────────────────────────────────

class TestTelegram:
    def test_post_message_no_token(self):
        """No token means no-op."""
        with patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "", "TELEGRAM_CHAT_INFRA": "123"}):
            # Should not raise
            post_message("TELEGRAM_CHAT_INFRA", "test message")

    def test_post_message_no_channel(self):
        """No channel means no-op."""
        with patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "token123", "TELEGRAM_CHAT_INFRA": ""}):
            post_message("TELEGRAM_CHAT_INFRA", "test message")

    @patch("hermes.tools.telegram.requests.post")
    def test_post_message_success(self, mock_post):
        """Message is sent when token and channel are set."""
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_post.return_value = mock_response

        with patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "bot123", "TELEGRAM_CHAT_TEST": "-100123"}):
            post_message("TELEGRAM_CHAT_TEST", "Hello!")

        mock_post.assert_called_once()
        call_kwargs = mock_post.call_args
        assert "bot123" in call_kwargs[0][0] or "bot123" in str(call_kwargs)

    @patch("hermes.tools.telegram.requests.post")
    def test_post_message_truncates_long_text(self, mock_post):
        """Long messages are truncated to 3500 chars."""
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_post.return_value = mock_response

        with patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "bot123", "TELEGRAM_CHAT_TEST": "-100123"}):
            post_message("TELEGRAM_CHAT_TEST", "A" * 5000)

        call_kwargs = mock_post.call_args
        sent_text = call_kwargs[1]["json"]["text"] if "json" in (call_kwargs[1] or {}) else call_kwargs.kwargs["json"]["text"]
        assert len(sent_text) <= 3500

    @patch("hermes.tools.telegram.requests.post")
    def test_post_message_handles_error(self, mock_post):
        """Telegram errors are silently ignored."""
        mock_post.side_effect = Exception("Network error")

        with patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "bot123", "TELEGRAM_CHAT_TEST": "-100123"}):
            # Should not raise
            post_message("TELEGRAM_CHAT_TEST", "test")
