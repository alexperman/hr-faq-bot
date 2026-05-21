"""Tests for backend services: rate_limit, kb_monitor, auth helpers, structured_logger."""
import pytest
import time
from unittest.mock import patch, MagicMock

from app.services.rate_limit import check_rate_limit, get_rate_limit_stats, _request_windows
from app.services.kb_monitor import record_kb_failure, get_kb_failure_stats, _kb_failure_events
from app.services.auth import (
    hash_password,
    verify_password,
    hash_api_key,
    verify_api_key,
    create_access_token,
    create_password_reset_token,
    verify_password_reset_token,
    get_auth_failure_stats,
    _record_auth_failure,
    _auth_failure_events,
)
from app.services.structured_logger import log_event, log_audit


# ─── Rate Limit Tests ─────────────────────────────────────────────────────────

class TestRateLimit:
    def setup_method(self):
        """Clear rate limit state between tests."""
        _request_windows.clear()

    def test_allows_under_limit(self):
        """Requests under limit pass through."""
        for i in range(19):
            check_rate_limit(user_id=100)
        # Should not raise

    def test_blocks_over_limit(self):
        """21st request in a minute is blocked."""
        from fastapi import HTTPException

        for i in range(20):
            check_rate_limit(user_id=200)

        with pytest.raises(HTTPException) as exc_info:
            check_rate_limit(user_id=200)
        assert exc_info.value.status_code == 429

    def test_different_users_independent(self):
        """Rate limits are per-user."""
        for i in range(20):
            check_rate_limit(user_id=300)

        # Different user should still be allowed
        check_rate_limit(user_id=301)

    def test_stats_returns_data(self):
        """Stats function returns expected structure."""
        stats = get_rate_limit_stats()
        assert "exceeded_last_60s" in stats
        assert "exceeded_last_24h" in stats
        assert "recent_exceeded_events" in stats

    def test_window_cleanup(self):
        """Old timestamps are cleaned up."""
        # Manually add old timestamps
        _request_windows[400] = [time.time() - 120]  # 2 minutes ago
        check_rate_limit(user_id=400)
        # Old timestamp should be cleaned, only new one remains
        assert len(_request_windows[400]) == 1


# ─── KB Monitor Tests ─────────────────────────────────────────────────────────

class TestKBMonitor:
    def setup_method(self):
        _kb_failure_events.clear()

    def test_record_failure(self):
        """Recording a failure adds to the list."""
        record_kb_failure(tenant_slug="test", reason="parse_error")
        stats = get_kb_failure_stats()
        assert stats["failures_total_recent"] == 1
        assert "parse_error" in stats["failures_by_reason_recent"]

    def test_multiple_failures(self):
        """Multiple failures are tracked."""
        record_kb_failure(tenant_slug="t1", reason="timeout")
        record_kb_failure(tenant_slug="t2", reason="timeout")
        record_kb_failure(tenant_slug="t1", reason="parse_error")

        stats = get_kb_failure_stats()
        assert stats["failures_total_recent"] == 3
        assert stats["failures_by_reason_recent"]["timeout"] == 2
        assert stats["failures_by_reason_recent"]["parse_error"] == 1

    def test_stats_empty(self):
        """Empty stats returns zeros."""
        stats = get_kb_failure_stats()
        assert stats["failures_total_recent"] == 0
        assert stats["failures_by_reason_recent"] == {}

    def test_history_limit(self):
        """Events are capped at history limit."""
        for i in range(250):
            record_kb_failure(tenant_slug="t", reason=f"err_{i}")
        stats = get_kb_failure_stats()
        assert stats["failures_total_recent"] <= 200


# ─── Auth Service Tests ───────────────────────────────────────────────────────

class TestAuthService:
    def test_hash_and_verify_password(self):
        """Password hashing and verification works."""
        hashed = hash_password("mypassword")
        assert verify_password("mypassword", hashed) is True
        assert verify_password("wrongpassword", hashed) is False

    def test_hash_and_verify_api_key(self):
        """API key hashing and verification works."""
        key = "riq_test_key_12345"
        hashed = hash_api_key(key)
        assert verify_api_key(key, hashed) is True
        assert verify_api_key("riq_wrong_key", hashed) is False

    def test_create_access_token(self):
        """Access token is created and decodable."""
        from jose import jwt
        from app.config import get_settings

        settings = get_settings()
        token = create_access_token(data={"user_id": 1, "tenant_slug": "test"})
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        assert payload["user_id"] == 1
        assert payload["tenant_slug"] == "test"
        assert payload["session_type"] == "web"

    def test_create_access_token_with_session_type(self):
        """Access token includes session type."""
        from jose import jwt
        from app.config import get_settings

        settings = get_settings()
        token = create_access_token(
            data={"user_id": 1, "tenant_slug": "test"},
            session_type="mcp",
        )
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        assert payload["session_type"] == "mcp"

    def test_password_reset_token_roundtrip(self):
        """Password reset token can be created and verified."""
        token = create_password_reset_token(user_id=42, email="test@example.com")
        payload = verify_password_reset_token(token)
        assert payload is not None
        assert payload["user_id"] == 42
        assert payload["email"] == "test@example.com"
        assert payload["purpose"] == "password_reset"

    def test_password_reset_token_invalid(self):
        """Invalid token returns None."""
        result = verify_password_reset_token("invalid-token")
        assert result is None

    def test_auth_failure_stats(self):
        """Auth failure tracking works."""
        _auth_failure_events.clear()
        _record_auth_failure("test_reason")
        _record_auth_failure("test_reason")
        _record_auth_failure("other_reason")

        stats = get_auth_failure_stats()
        assert stats["failures_total_recent"] == 3
        assert stats["failures_by_reason_recent"]["test_reason"] == 2
        assert stats["failures_by_reason_recent"]["other_reason"] == 1
        _auth_failure_events.clear()


# ─── Structured Logger Tests ──────────────────────────────────────────────────

class TestStructuredLogger:
    def test_log_event(self, capsys):
        """log_event writes JSON to stdout."""
        log_event(event="test_event", severity="info", extra_field="value")
        captured = capsys.readouterr()
        import json
        record = json.loads(captured.out.strip())
        assert record["event"] == "test_event"
        assert record["severity"] == "info"
        assert record["extra_field"] == "value"
        assert "timestamp" in record

    def test_log_audit(self, capsys):
        """log_audit writes audit record."""
        log_audit(action="test_action", actor="test_actor")
        captured = capsys.readouterr()
        import json
        record = json.loads(captured.out.strip())
        assert record["event"] == "audit"
        assert record["action"] == "test_action"
        assert record["actor"] == "test_actor"

    def test_log_event_filters_none(self, capsys):
        """None values are filtered from log output."""
        log_event(event="test", severity="info", null_field=None)
        captured = capsys.readouterr()
        import json
        record = json.loads(captured.out.strip())
        assert "null_field" not in record
