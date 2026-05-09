from __future__ import annotations

from hermes.tools.api_client import from_env


def system_health() -> dict:
    c = from_env()
    return c.get_json("/admin/system/health")


def system_logs() -> dict:
    c = from_env()
    return c.get_json("/admin/system/logs")


def system_stats() -> dict:
    c = from_env()
    return c.get_json("/admin/system/stats")


def deploy_status() -> dict:
    c = from_env()
    return c.get_json("/admin/deploy/status")


def paypal_status() -> dict:
    c = from_env()
    return c.get_json("/admin/paypal/status")
