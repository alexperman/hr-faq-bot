import argparse
import json
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from pathlib import Path

from hermes.tools.paths import memory_root
from hermes.tools.storage import write_json, utc_now_iso
from hermes.tools.env import load_env
from hermes.tools.telegram import post_message


INCIDENT_DIR = "deployment_incidents"
DEPLOYMENT_DIR = "deployments"
GROWTH_DIR = "growth_experiments"
SUMMARIES_DIR = "daily_summaries"


@dataclass
class Incident:
    incident: str = ""
    severity: str = ""
    cause: str = ""
    fix: str = ""
    timestamp: str = ""


def _parse_incident(obj: dict) -> Incident:
    return Incident(
        incident=str(obj.get("incident") or ""),
        severity=str(obj.get("severity") or ""),
        cause=str(obj.get("cause") or ""),
        fix=str(obj.get("fix") or ""),
        timestamp=str(obj.get("timestamp") or ""),
    )


def _safe_fromiso(value: str) -> datetime | None:
    try:
        # Handle timezone-less ISO strings from older runs.
        if value.endswith("Z"):
            value = value.replace("Z", "+00:00")
        dt = datetime.fromisoformat(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def _load_json_files(dir_path: Path) -> list[dict]:
    if not dir_path.exists():
        return []
    out: list[dict] = []
    for p in sorted(dir_path.glob("*.json"), key=lambda x: x.stat().st_mtime):
        try:
            out.append(json.loads(p.read_text(encoding="utf-8")))
        except Exception:
            continue
    return out


def run_memory_maintenance(args: argparse.Namespace) -> None:
    # Local-only memory processing (no secrets).
    load_env()

    root = memory_root()
    incident_dir = root / INCIDENT_DIR
    deployments_dir = root / DEPLOYMENT_DIR
    growth_dir = root / GROWTH_DIR
    summaries_dir = root / SUMMARIES_DIR

    incident_dir.mkdir(parents=True, exist_ok=True)
    deployments_dir.mkdir(parents=True, exist_ok=True)
    growth_dir.mkdir(parents=True, exist_ok=True)
    summaries_dir.mkdir(parents=True, exist_ok=True)

    # Pull incidents
    incident_objs = _load_json_files(incident_dir)
    incidents: list[Incident] = [_parse_incident(o) for o in incident_objs]

    now = datetime.now(timezone.utc)
    window_start = now - timedelta(days=1)

    recent: list[Incident] = []
    for inc in incidents:
        dt = _safe_fromiso(inc.timestamp)
        if not dt:
            # fall back to ignore timestamp-less items
            continue
        if dt >= window_start:
            recent.append(inc)

    # Pull latest health snapshot(s) to infer "successful fixes".
    health_snapshots = _load_json_files(deployments_dir)
    # Only keep snapshots that match our expected structure.
    health_items = [h for h in health_snapshots if h.get("type") == "health_snapshot"]

    latest_health = max(
        health_items,
        key=lambda x: _safe_fromiso(x.get("at") or "") or datetime.fromtimestamp(0, tz=timezone.utc),
        default=None,
    )

    db_ok = bool((latest_health or {}).get("health", {}).get("ok"))
    paypal_ok = bool((latest_health or {}).get("health", {}).get("paypal", {}).get("webhook_processing_ok"))
    kb_docs_total = int((latest_health or {}).get("health", {}).get("kb", {}).get("docs_total") or 0)

    # Heuristic: if we had an incident recently and latest health is OK, mark as likely resolved.
    successful_fixes: list[dict] = []
    if recent and db_ok and paypal_ok and kb_docs_total is not None:
        successful_fixes.append(
            {
                "time_window": "last_24h",
                "signal": "admin health ok + webhook ok observed",
                "notes": "Latest health snapshot reports ok=true and webhook_processing_ok=true after recent incidents.",
            }
        )

    # Compress repetitive operational data: summarize top recurring causes.
    def _norm(s: str) -> str:
        s = (s or "").strip().lower()
        # light normalization
        for token in ["render", "replyiq", "postgres", "database"]:
            s = s.replace(token, token)
        return s

    cause_counts: dict[str, int] = {}
    incident_counts: dict[str, int] = {}
    for inc in recent:
        inc_name = (inc.incident or "unknown").strip()
        incident_counts[inc_name] = incident_counts.get(inc_name, 0) + 1

        c = _norm(inc.cause)
        # Use a compact key: first clause
        key = c.split(".")[0][:120] if c else ""
        if key:
            cause_counts[key] = cause_counts.get(key, 0) + 1

    recurring_issues = {
        "incident_top": sorted(incident_counts.items(), key=lambda x: x[1], reverse=True)[:5],
        "cause_top": sorted(cause_counts.items(), key=lambda x: x[1], reverse=True)[:5],
    }

    # Track recurring product issues (inferred from incident text/cause keywords).
    product_issue_signals: list[dict] = []
    recent_text = "\n".join([
        f"{r.incident}\n{r.cause}\n{r.fix}" for r in recent
    ]).lower()

    if "webhook" in recent_text or "paypal" in recent_text:
        product_issue_signals.append(
            {
                "issue": "subscription gating via PayPal webhook",
                "evidence": "recent incidents mention paypal/webhook verification",
            }
        )
    if "rate" in recent_text:
        product_issue_signals.append(
            {
                "issue": "rate-limit anomalies",
                "evidence": "recent incidents mention rate limit",
            }
        )
    if "kb" in recent_text or "knowledge" in recent_text:
        product_issue_signals.append(
            {
                "issue": "KB ingestion / corpus readiness",
                "evidence": "recent incidents mention kb corpus empty or stale documents",
            }
        )

    # Track onboarding friction (no direct onboarding telemetry yet).
    # We preserve actionable intelligence only, so we keep it conservative.
    onboarding_friction = {
        "observed_signals": [],
        "notes": "No explicit onboarding friction telemetry captured in hermes memory yet.",
    }

    # Optional: summarize recent growth drafts volume as a proxy for outreach throughput.
    growth_files = list(growth_dir.glob("*.json"))
    growth_volume = len(growth_files)

    summary = {
        "type": "memory_agent_daily_summary",
        "at": utc_now_iso(),
        "window": "last_24h",
        "recent_incidents_count": len(recent),
        "successful_fixes": successful_fixes,
        "recurring_operational_data": recurring_issues,
        "recurring_product_issue_signals": product_issue_signals,
        "onboarding_friction": onboarding_friction,
        "current_readiness": {
            "admin_db_ok": db_ok,
            "paypal_webhook_ok": paypal_ok,
            "kb_docs_total": kb_docs_total,
        },
        "growth_drafts_files_total": growth_volume,
        "preserved_next_steps": [
            "If PayPal webhook incidents recur, ensure PAYPAL_WEBHOOK_ID is configured and signature verification succeeds.",
            "If KB corpus is empty for active tenants, focus on KB ingestion steps for go-live.",
            "If rate-limit anomalies spike, consider production rate-limiter improvements (after rollout success).",
        ],
    }

    out_path = summaries_dir / f"memory_agent_daily_{now.date().isoformat()}.json"
    write_json(out_path, summary)

    post_message(
        "TELEGRAM_CHAT_MEMORY",
        f"🧠 Daily ops summary ({now.date().isoformat()}), incidents={len(recent)}, fixes={len(successful_fixes)}",
    )

    # Persist successful fixes into required memory domain.
    try:
        fixes_dir = memory_root() / "successful_fixes"
        fixes_dir.mkdir(parents=True, exist_ok=True)
        fixes_path = fixes_dir / f"successful_fixes_{now.date().isoformat()}.json"
        write_json(fixes_path, {"window": "last_24h", "successful_fixes": successful_fixes})
    except Exception:
        pass

    # Keep stdout quiet unless explicitly requested.
    if not getattr(args, "dry_run", False):
        print(f"[memory-agent] wrote {out_path}")
