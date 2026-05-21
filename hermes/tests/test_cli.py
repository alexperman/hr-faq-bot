"""Tests for the hermes CLI (hermes/cli.py)."""
import pytest
import sys
import os
from unittest.mock import patch, MagicMock
from argparse import Namespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from hermes.cli import main


class TestCLICommands:
    """Test that CLI commands dispatch correctly."""

    @patch("hermes.cli.run_infra_health_check")
    def test_infra_agent_health(self, mock_run):
        with patch("sys.argv", ["hermes", "--dry-run", "infra-agent-health"]):
            main()
        mock_run.assert_called_once()

    @patch("hermes.cli.run_infra_deploy_verification")
    def test_infra_agent_deploy(self, mock_run):
        with patch("sys.argv", ["hermes", "--dry-run", "infra-agent-deploy"]):
            main()
        mock_run.assert_called_once()

    @patch("hermes.cli.run_infra_incident_summarization")
    def test_infra_agent_summarize(self, mock_run):
        with patch("sys.argv", ["hermes", "--dry-run", "infra-agent-summarize"]):
            main()
        mock_run.assert_called_once()

    @patch("hermes.cli.run_infra_health_check")
    def test_infra_agent_compat(self, mock_run):
        """Backwards-compat 'infra-agent' command."""
        with patch("sys.argv", ["hermes", "--dry-run", "infra-agent"]):
            main()
        mock_run.assert_called_once()

    @patch("hermes.cli.run_memory_maintenance")
    def test_memory_agent(self, mock_run):
        with patch("sys.argv", ["hermes", "--dry-run", "memory-agent"]):
            main()
        mock_run.assert_called_once()

    @patch("hermes.cli.run_outreach_generation")
    def test_growth_agent(self, mock_run):
        with patch("sys.argv", ["hermes", "--dry-run", "growth-agent"]):
            main()
        mock_run.assert_called_once()

    @patch("hermes.cli.run_analytics")
    def test_analytics_agent(self, mock_run):
        with patch("sys.argv", ["hermes", "--dry-run", "analytics-agent"]):
            main()
        mock_run.assert_called_once()

    @patch("hermes.cli.run_kb_assist")
    def test_kb_agent(self, mock_run):
        with patch("sys.argv", ["hermes", "--dry-run", "kb-agent"]):
            main()
        mock_run.assert_called_once()

    @patch("hermes.cli.run_support")
    def test_support_agent(self, mock_run):
        with patch("sys.argv", ["hermes", "--dry-run", "support-agent"]):
            main()
        mock_run.assert_called_once()

    @patch("hermes.cli.run_product_recommendations")
    def test_product_agent(self, mock_run):
        with patch("sys.argv", ["hermes", "--dry-run", "product-agent"]):
            main()
        mock_run.assert_called_once()

    @patch("hermes.cli.run_leads_outreach")
    def test_leads_agent(self, mock_run):
        with patch("sys.argv", ["hermes", "--dry-run", "leads-agent"]):
            main()
        mock_run.assert_called_once()

    def test_no_command_exits(self):
        """No command shows help and exits."""
        with patch("sys.argv", ["hermes"]):
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 2

    def test_invalid_command_exits(self):
        """Invalid command exits with error."""
        with patch("sys.argv", ["hermes", "nonexistent-command"]):
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 2
