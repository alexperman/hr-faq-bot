import argparse
import json
from datetime import datetime, timezone

from hermes.tools.env import load_env
from hermes.tools.paths import memory_root
from hermes.tools.replyiq_admin import (
    system_health,
    system_logs,
    system_stats,
    deploy_status,
    paypal_status,
)
from hermes.tools.storage import write_json, utc_now_iso
from hermes.tools.telegram import post_message


INCIDENT_SCHEMA_KEYS = ["incident", "severity", "cause", "fix", "timestamp"]


def _now_iso() -> str:
    return utc_now_iso()


def _write_incident(incident: dict) -> None:
    # Enforce schema keys (never expose secrets; just operational text).
    out = {k: incident.get(k, "") for k in INCIDENT_SCHEMA_KEYS}
    out["timestamp"] = incident.get("timestamp") or _now_iso()

    incidents_dir = memory_root() / "deployment_incidents"
    ts = datetime.now(timezone.utc).isoformat().replace(":", "-")
    path = incidents_dir / f"incident_{ts}.json"
    write_json(path, out)

    inc_text = (out.get("incident") or "").lower()
    if "paypal" in inc_text or "webhook" in inc_text:
        failed_dir = memory_root() / "failed_webhooks"
        failed_dir.mkdir(parents=True, exist_ok=True)
        failed_path = failed_dir / f"failed_webhook_{ts}.json"
        write_json(failed_path, out)

    severity = (out.get("severity") or "").strip().lower()
    channel = "TELEGRAM_CHAT_CRITICAL" if severity in ("critical", "high") else "TELEGRAM_CHAT_INFRA"
    post_message(
        channel,
        f"{out.get('incident','Infrastructure incident')} | severity={out.get('severity','')} | {out.get('timestamp','')}",
    )


def _severity_from_flags(flags: dict) -> str | None:
    if flags.get("db_ok") is False:
        return "critical"
    if flags.get("paypal_ok") is False:
        return "high"

    if (
        flags.get("auth_anomaly")
        or flags.get("kb_ingest_anomaly")
        or flags.get("tenants_empty_kb")
    ):
        return "medium"

    if flags.get("rate_limit_anomaly"):
        return "medium"
    if flags.get("kb_stale"):
        return "low"
    return None


def run_infra_health_check(args: argparse.Namespace) -> None:
    load_env()

    health = system_health()
    stats = system_stats()
    logs = system_logs()  # structured logs (safe aggregates)

    db_ok = bool(health.get("db", {}).get("ok"))
    paypal_ok = bool(health.get("paypal", {}).get("webhook_processing_ok"))

    exceeded_60s = int(health.get("rate_limit", {}).get("exceeded_last_60s") or 0)
    # Conservative threshold to avoid noise
    rate_limit_anomaly = exceeded_60s >= 10

    docs_total = int(health.get("kb", {}).get("docs_total") or 0)
    kb_warning = health.get("kb", {}).get("warning")

    tenants = health.get("tenants", {}) or {}
    tenants_empty_kb = int(tenants.get("active_tenants_empty_kb") or 0)
    tenants_stale_kb = int(tenants.get("active_tenants_stale_kb_over_7d") or 0)

    auth_failures_total = int((health.get("auth", {}) or {}).get("failures_total_recent") or 0)
    kb_ingest_failures_total = int((health.get("kb_ingest", {}) or {}).get("failures_total_recent") or 0)

    auth_anomaly = auth_failures_total >= 20
    kb_ingest_anomaly = kb_ingest_failures_total >= 5

    kb_corpus_empty = bool(tenants_empty_kb > 0 or docs_total == 0)

    kb_last_updated = health.get("kb", {}).get("docs_last_updated_at")
    kb_stale = False
    if kb_last_updated:
        try:
            dt = datetime.fromisoformat(kb_last_updated.replace("Z", "+00:00"))
            kb_stale = (datetime.now(timezone.utc) - dt).days >= 7
        except Exception:
            kb_stale = False

    kb_stale = bool(kb_stale or tenants_stale_kb > 0)

    flags = {
        "db_ok": db_ok,
        "paypal_ok": paypal_ok,
        "rate_limit_anomaly": rate_limit_anomaly,
        "kb_corpus_empty": bool(kb_warning is not None or kb_corpus_empty),
        "kb_stale": kb_stale,
        "auth_anomaly": auth_anomaly,
        "kb_ingest_anomaly": kb_ingest_anomaly,
        "tenants_empty_kb": tenants_empty_kb > 0,
    }

    severity = _severity_from_flags(flags)

    incident = None
    if severity == "critical":
        incident = {
            "incident": "Database connectivity failed",
            "severity": severity,
            "cause": "Admin health check could not ping the DB",
            "fix": "Check Render Postgres connection (DATABASE_URL) and verify the service can reach the DB.",
            "timestamp": _now_iso(),
        }
    elif severity == "high" and not paypal_ok:
        incident = {
            "incident": "PayPal webhook processing unhealthy",
            "severity": severity,
            "cause": "Latest webhook verification did not pass (or no successful verification observed).",
            "fix": "Verify PAYPAL_WEBHOOK_ID and PayPal webhook signature verification configuration; inspect last webhook verification attempts in admin logs.",
            "timestamp": _now_iso(),
        }
    elif severity == "medium" and (flags.get("auth_anomaly") or flags.get("kb_ingest_anomaly")):
        incident = {
            "incident": "Auth failures and/or KB ingestion failures detected",
            "severity": severity,
            "cause": f"auth_failures_total_recent={auth_failures_total}, kb_ingest_failures_total_recent={kb_ingest_failures_total}",
            "fix": "Inspect admin system logs for recent auth/kb ingestion failures; ensure client auth flow and KB document creation path work end-to-end.",
            "timestamp": _now_iso(),
        }
    elif severity == "medium" and rate_limit_anomaly:
        incident = {
            "incident": "Rate-limit anomalies detected",
            "severity": severity,
            "cause": f"exceeded_last_60s={exceeded_60s} in admin system health",
            "fix": "Investigate /chat ask usage patterns and consider tuning rate limit strategy (e.g., move to Redis) after verifying product demand.",
            "timestamp": _now_iso(),
        }
    elif severity == "medium" and flags.get("kb_corpus_empty"):
        incident = {
            "incident": "KB corpus may be empty or not populated",
            "severity": severity,
            "cause": f"docs_total={docs_total} (KB docs corpus empty) or KB warning present.",
            "fix": "Confirm KB ingestion/upload flows are working for active tenants; ensure KB documents are being added (manual upload or ingestion).",
            "timestamp": _now_iso(),
        }
    elif severity == "low" and kb_stale:
        incident = {
            "incident": "KB appears stale (no recent document updates)",
            "severity": severity,
            "cause": f"docs_last_updated_at={kb_last_updated}",
            "fix": "Refresh/update key handbook and policy documents so answers remain accurate.",
            "timestamp": _now_iso(),
        }

    if incident:
        _write_incident(incident)

    if getattr(args, "dry_run", False):
        return

    # Always store a lightweight health snapshot (not an incident) for debugging.
    deployments_dir = memory_root() / "deployments"
    ts_day = datetime.utcnow().date().isoformat()
    out = {
        "type": "health_snapshot",
        "at": _now_iso(),
        "health": health,
        "stats": {k: v for k, v in stats.items() if k != "recent"},
        "logs": {k: v for k, v in logs.items() if k in ("recent_webhook_events", "recent_rate_limit_exceeds")},
    }
    write_json(deployments_dir / f"health_snapshot_{ts_day}.json", out)
    print("[infra-agent-health] completed")


def run_infra_deploy_verification(args: argparse.Namespace) -> None:
    load_env()

    ds = deploy_status()
    ps = paypal_status()
    health = system_health()

    # Track last seen deploy identity (safe, no secrets).
    deployments_dir = memory_root() / "deployments"
    state_path = deployments_dir / "deploy_state.json"

    state = {}
    try:
        if state_path.exists():
            state = json.loads(state_path.read_text(encoding="utf-8"))
    except Exception:
        state = {}

    new_identity = {
        "render_service_name": (ds.get("environment") or {}).get("RENDER_SERVICE_NAME"),
        "render_git_commit": (ds.get("environment") or {}).get("RENDER_GIT_COMMIT"),
        "render_build_id": (ds.get("environment") or {}).get("RENDER_BUILD_ID"),
    }

    last_identity = state.get("identity")

    changed = last_identity is not None and new_identity != last_identity

    if changed and not health.get("ok"):
        _write_incident(
            {
                "incident": "Deployment health regression",
                "severity": "high" if not health.get("ok") else "medium",
                "cause": "New Render build detected while admin health reported failing checks.",
                "fix": "Escalate to production owner. Verify DATABASE_URL and PayPal settings for the new build; review admin system logs.",
                "timestamp": _now_iso(),
            }
        )

    state.update({"identity": new_identity, "at": _now_iso(), "deploy_status": ds, "paypal_status": ps})
    write_json(state_path, state)

    if not getattr(args, "dry_run", False):
        print("[infra-agent-deploy] completed")


def run_infra_incident_summarization(args: argparse.Namespace) -> None:
    load_env()

    incidents_dir = memory_root() / "deployment_incidents"
    summaries_dir = memory_root() / "daily_summaries"

    now = datetime.now(timezone.utc)
    cutoff = now.timestamp() - 3600

    recent: list[dict] = []
    for p in sorted(incidents_dir.glob("incident_*.json"), key=lambda x: x.stat().st_mtime):
        try:
            if p.stat().st_mtime < cutoff:
                continue
            recent.append(json.loads(p.read_text(encoding="utf-8")))
        except Exception:
            continue

    by_sev: dict[str, int] = {}
    for inc in recent:
        sev = (inc.get("severity") or "").strip() or "unknown"
        by_sev[sev] = by_sev.get(sev, 0) + 1

    summary = {
        "type": "infra_incident_summary",
        "at": _now_iso(),
        "count": len(recent),
        "by_severity": by_sev,
        "incidents": recent[-20:],
        "recommended_next_steps": [
            "Review incident context via RelyIQ admin logs and system health endpoints.",
            "Only apply config changes with explicit approval (no automatic restarts/redeploys).",
        ],
    }

    out_path = summaries_dir / f"infra_incidents_{now.date().isoformat()}_{now.hour:02d}.json"
    write_json(out_path, summary)

    post_message(
        "TELEGRAM_CHAT_INFRA",
        f"🏗️ Infra incident summary ({now.date().isoformat()} hour {now.hour:02d}), count={len(recent)}",
    )

    if not getattr(args, "dry_run", False):
        print(f"[infra-agent-summarize] wrote {out_path}")
