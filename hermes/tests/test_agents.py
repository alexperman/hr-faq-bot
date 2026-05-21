"""Tests for hermes agents."""
import json
import os
import pytest
import tempfile
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch, MagicMock

import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from hermes.agents.infra_agent import (
    run_infra_health_check,
    run_infra_deploy_verification,
    run_infra_incident_summarization,
    _severity_from_flags,
    _write_incident,
)
from hermes.agents.memory_agent import run_memory_maintenance
from hermes.agents.growth_agent import run_outreach_generation
from hermes.agents.analytics_agent import run_analytics
from hermes.agents.kb_agent import run_kb_assist
from hermes.agents.support_agent import run_support
from hermes.agents.product_agent import run_product_recommendations
from hermes.agents.leads_agent import run_leads_outreach, _infer_lang_from_email, _add_utm


# ─── Infra Agent Tests ────────────────────────────────────────────────────────

class TestInfraAgent:
    def test_severity_from_flags_critical(self):
        flags = {"db_ok": False, "paypal_ok": True}
        assert _severity_from_flags(flags) == "critical"

    def test_severity_from_flags_high(self):
        flags = {"db_ok": True, "paypal_ok": False}
        assert _severity_from_flags(flags) == "high"

    def test_severity_from_flags_medium_auth(self):
        flags = {"db_ok": True, "paypal_ok": True, "auth_anomaly": True}
        assert _severity_from_flags(flags) == "medium"

    def test_severity_from_flags_medium_rate_limit(self):
        flags = {"db_ok": True, "paypal_ok": True, "rate_limit_anomaly": True}
        assert _severity_from_flags(flags) == "medium"

    def test_severity_from_flags_low(self):
        flags = {"db_ok": True, "paypal_ok": True, "kb_stale": True}
        assert _severity_from_flags(flags) == "low"

    def test_severity_from_flags_none(self):
        flags = {"db_ok": True, "paypal_ok": True}
        assert _severity_from_flags(flags) is None

    @patch("hermes.agents.infra_agent.post_message")
    @patch("hermes.agents.infra_agent.write_json")
    @patch("hermes.agents.infra_agent.memory_root")
    def test_write_incident(self, mock_root, mock_write, mock_post):
        mock_root.return_value = Path(tempfile.mkdtemp())
        incident = {
            "incident": "Test incident",
            "severity": "high",
            "cause": "Test cause",
            "fix": "Test fix",
            "timestamp": "2024-01-01T00:00:00+00:00",
        }
        _write_incident(incident)
        mock_write.assert_called()
        mock_post.assert_called()

    @patch("hermes.agents.infra_agent.post_message")
    @patch("hermes.agents.infra_agent.write_json")
    @patch("hermes.agents.infra_agent.memory_root")
    def test_write_incident_paypal(self, mock_root, mock_write, mock_post):
        """PayPal incidents also write to failed_webhooks."""
        tmp = Path(tempfile.mkdtemp())
        mock_root.return_value = tmp
        incident = {
            "incident": "PayPal webhook failure",
            "severity": "high",
            "cause": "Verification failed",
            "fix": "Check config",
            "timestamp": "2024-01-01T00:00:00+00:00",
        }
        _write_incident(incident)
        # Should write to both deployment_incidents and failed_webhooks
        assert mock_write.call_count >= 2

    @patch("hermes.agents.infra_agent.system_logs")
    @patch("hermes.agents.infra_agent.system_stats")
    @patch("hermes.agents.infra_agent.system_health")
    @patch("hermes.agents.infra_agent.load_env")
    @patch("hermes.agents.infra_agent.write_json")
    @patch("hermes.agents.infra_agent.memory_root")
    def test_run_infra_health_check_dry_run(self, mock_root, mock_write, mock_load, mock_health, mock_stats, mock_logs):
        mock_root.return_value = Path(tempfile.mkdtemp())
        mock_health.return_value = {
            "ok": True,
            "db": {"ok": True},
            "paypal": {"webhook_processing_ok": True},
            "rate_limit": {"exceeded_last_60s": 0},
            "kb": {"docs_total": 5, "warning": None, "docs_last_updated_at": None},
            "tenants": {"active_tenants_empty_kb": 0, "active_tenants_stale_kb_over_7d": 0},
            "auth": {"failures_total_recent": 0},
            "kb_ingest": {"failures_total_recent": 0},
        }
        mock_stats.return_value = {}
        mock_logs.return_value = {}

        args = Namespace(dry_run=True)
        run_infra_health_check(args)
        # Should not write health snapshot in dry_run
        # (it returns early before writing)

    @patch("hermes.agents.infra_agent.deploy_status")
    @patch("hermes.agents.infra_agent.paypal_status")
    @patch("hermes.agents.infra_agent.system_health")
    @patch("hermes.agents.infra_agent.load_env")
    @patch("hermes.agents.infra_agent.write_json")
    @patch("hermes.agents.infra_agent.memory_root")
    def test_run_infra_deploy_verification(self, mock_root, mock_write, mock_load, mock_health, mock_paypal, mock_deploy):
        tmp = Path(tempfile.mkdtemp())
        mock_root.return_value = tmp
        (tmp / "deployments").mkdir(parents=True)

        mock_deploy.return_value = {"environment": {}}
        mock_paypal.return_value = {}
        mock_health.return_value = {"ok": True}

        args = Namespace(dry_run=True)
        run_infra_deploy_verification(args)
        mock_write.assert_called()

    @patch("hermes.agents.infra_agent.post_message")
    @patch("hermes.agents.infra_agent.write_json")
    @patch("hermes.agents.infra_agent.load_env")
    @patch("hermes.agents.infra_agent.memory_root")
    def test_run_infra_incident_summarization(self, mock_root, mock_load, mock_write, mock_post):
        tmp = Path(tempfile.mkdtemp())
        mock_root.return_value = tmp
        (tmp / "deployment_incidents").mkdir(parents=True)
        (tmp / "daily_summaries").mkdir(parents=True)

        args = Namespace(dry_run=True)
        run_infra_incident_summarization(args)


# ─── Memory Agent Tests ───────────────────────────────────────────────────────

class TestMemoryAgent:
    @patch("hermes.agents.memory_agent.post_message")
    @patch("hermes.agents.memory_agent.load_env")
    @patch("hermes.agents.memory_agent.memory_root")
    def test_run_memory_maintenance(self, mock_root, mock_load, mock_post):
        tmp = Path(tempfile.mkdtemp())
        mock_root.return_value = tmp

        args = Namespace(dry_run=True)
        run_memory_maintenance(args)

        # Should create summary file
        summaries = list((tmp / "daily_summaries").glob("memory_agent_daily_*.json"))
        assert len(summaries) == 1

        data = json.loads(summaries[0].read_text())
        assert data["type"] == "memory_agent_daily_summary"
        assert "recent_incidents_count" in data


# ─── Growth Agent Tests ───────────────────────────────────────────────────────

class TestGrowthAgent:
    @patch("hermes.agents.growth_agent.post_message")
    @patch("hermes.agents.growth_agent.load_env")
    @patch("hermes.agents.growth_agent.memory_root")
    def test_run_outreach_generation(self, mock_root, mock_load, mock_post):
        tmp = Path(tempfile.mkdtemp())
        mock_root.return_value = tmp

        args = Namespace(dry_run=True, link="https://example.com", first_name="Alex")
        run_outreach_generation(args)

        # Should create growth drafts
        drafts = list((tmp / "growth_experiments").glob("growth_drafts_*.json"))
        assert len(drafts) == 1

        data = json.loads(drafts[0].read_text())
        assert data["type"] == "growth_agent_daily_drafts"
        assert "en" in data["drafts"]
        assert "es" in data["drafts"]
        assert "de" in data["drafts"]


# ─── Analytics Agent Tests ────────────────────────────────────────────────────

class TestAnalyticsAgent:
    @patch("hermes.agents.analytics_agent.load_env")
    @patch("hermes.agents.analytics_agent.memory_root")
    def test_run_analytics(self, mock_root, mock_load):
        tmp = Path(tempfile.mkdtemp())
        mock_root.return_value = tmp

        args = Namespace(dry_run=True)
        run_analytics(args)

        summaries = list((tmp / "daily_summaries").glob("analytics_*.json"))
        assert len(summaries) == 1
        data = json.loads(summaries[0].read_text())
        assert data["type"] == "analytics_snapshot"
        assert data["status"] == "stub"


# ─── KB Agent Tests ───────────────────────────────────────────────────────────

class TestKBAgent:
    @patch("hermes.agents.kb_agent.load_env")
    @patch("hermes.agents.kb_agent.memory_root")
    def test_run_kb_assist(self, mock_root, mock_load):
        tmp = Path(tempfile.mkdtemp())
        mock_root.return_value = tmp

        args = Namespace(dry_run=True)
        run_kb_assist(args)

        recs = list((tmp / "product_recommendations").glob("kb_assist_*.json"))
        assert len(recs) == 1
        data = json.loads(recs[0].read_text())
        assert data["type"] == "kb_assist"
        assert len(data["suggestions"]) > 0


# ─── Support Agent Tests ──────────────────────────────────────────────────────

class TestSupportAgent:
    @patch("hermes.agents.support_agent.load_env")
    @patch("hermes.agents.support_agent.memory_root")
    def test_run_support(self, mock_root, mock_load):
        tmp = Path(tempfile.mkdtemp())
        mock_root.return_value = tmp

        args = Namespace(dry_run=True)
        run_support(args)

        summaries = list((tmp / "daily_summaries").glob("support_*.json"))
        assert len(summaries) == 1
        data = json.loads(summaries[0].read_text())
        assert data["type"] == "support_summary"


# ─── Product Agent Tests ──────────────────────────────────────────────────────

class TestProductAgent:
    @patch("hermes.agents.product_agent.post_message")
    @patch("hermes.agents.product_agent.load_env")
    @patch("hermes.agents.product_agent.memory_root")
    def test_run_product_recommendations(self, mock_root, mock_load, mock_post):
        tmp = Path(tempfile.mkdtemp())
        mock_root.return_value = tmp

        args = Namespace(dry_run=True)
        run_product_recommendations(args)

        recs = list((tmp / "product_recommendations").glob("product_recs_*.json"))
        assert len(recs) == 1
        data = json.loads(recs[0].read_text())
        assert data["type"] == "product_agent_recommendations"
        assert len(data["recommendations"]) > 0


# ─── Leads Agent Tests ────────────────────────────────────────────────────────

class TestLeadsAgent:
    def test_infer_lang_from_email_de(self):
        assert _infer_lang_from_email("user@company.de") == "de"
        assert _infer_lang_from_email("user@company.at") == "de"

    def test_infer_lang_from_email_es(self):
        assert _infer_lang_from_email("user@company.es") == "es"

    def test_infer_lang_from_email_default(self):
        assert _infer_lang_from_email("user@company.com") == "en"
        assert _infer_lang_from_email("user@company.co.uk") == "en"

    def test_add_utm(self):
        url = "https://example.com/product"
        result = _add_utm(url, {"utm_source": "lead", "utm_medium": "outreach"})
        assert "utm_source=lead" in result
        assert "utm_medium=outreach" in result

    def test_add_utm_empty_url(self):
        assert _add_utm("", {"utm_source": "test"}) == ""

    @patch("hermes.agents.leads_agent.post_message")
    @patch("hermes.agents.leads_agent.leads_recent")
    @patch("hermes.agents.leads_agent.load_env")
    @patch("hermes.agents.leads_agent.memory_root")
    def test_run_leads_outreach_no_leads(self, mock_root, mock_load, mock_leads, mock_post):
        tmp = Path(tempfile.mkdtemp())
        mock_root.return_value = tmp
        mock_leads.return_value = {"leads": []}

        args = Namespace(dry_run=False, link="https://example.com", limit=30, since_hours=24, default_lang="en")
        run_leads_outreach(args)

        mock_post.assert_called()

    @patch("hermes.agents.leads_agent.post_message")
    @patch("hermes.agents.leads_agent.leads_recent")
    @patch("hermes.agents.leads_agent.load_env")
    @patch("hermes.agents.leads_agent.memory_root")
    def test_run_leads_outreach_with_leads(self, mock_root, mock_load, mock_leads, mock_post):
        tmp = Path(tempfile.mkdtemp())
        mock_root.return_value = tmp
        mock_leads.return_value = {
            "leads": [
                {"id": 1, "email": "lead1@example.com", "source": "landing", "created_at": "2024-01-01T00:00:00Z"},
                {"id": 2, "email": "lead2@company.de", "source": "referral", "created_at": "2024-01-01T00:00:00Z"},
            ]
        }

        args = Namespace(dry_run=False, link="https://example.com/product", limit=30, since_hours=24, default_lang="en")
        run_leads_outreach(args)

        # Should create draft files
        drafts = list((tmp / "outreach" / "drafts").glob("lead_*.json"))
        assert len(drafts) == 2

        # Check language inference
        draft1 = json.loads(drafts[0].read_text())
        draft2 = json.loads(drafts[1].read_text())
        langs = {draft1["language"], draft2["language"]}
        assert "en" in langs
        assert "de" in langs

    @patch("hermes.agents.leads_agent.post_message")
    @patch("hermes.agents.leads_agent.leads_recent")
    @patch("hermes.agents.leads_agent.load_env")
    @patch("hermes.agents.leads_agent.memory_root")
    def test_run_leads_outreach_skips_processed(self, mock_root, mock_load, mock_leads, mock_post):
        """Already-processed leads are skipped."""
        tmp = Path(tempfile.mkdtemp())
        mock_root.return_value = tmp

        # Pre-populate state
        state_dir = tmp / "outreach"
        state_dir.mkdir(parents=True)
        state_path = state_dir / "leads_outreach_state.json"
        state_path.write_text(json.dumps({"processed_ids": ["1"], "updated_at": "2024-01-01"}))

        mock_leads.return_value = {
            "leads": [
                {"id": 1, "email": "old@example.com", "source": "landing", "created_at": "2024-01-01T00:00:00Z"},
                {"id": 2, "email": "new@example.com", "source": "landing", "created_at": "2024-01-01T00:00:00Z"},
            ]
        }

        args = Namespace(dry_run=False, link="https://example.com", limit=30, since_hours=24, default_lang="en")
        run_leads_outreach(args)

        # Only lead 2 should be drafted
        drafts = list((tmp / "outreach" / "drafts").glob("lead_*.json"))
        assert len(drafts) == 1
        assert "lead_2" in drafts[0].name
