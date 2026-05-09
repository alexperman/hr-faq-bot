import argparse
from datetime import datetime
from hermes.tools.env import load_env
from hermes.tools.api_client import from_env
from hermes.tools.paths import memory_root
from hermes.tools.storage import write_json, utc_now_iso


def _safe_get(dct, *keys, default=None):
    cur = dct
    for k in keys:
        if not isinstance(cur, dict) or k not in cur:
            return default
        cur = cur[k]
    return cur


def run_infra_check(args: argparse.Namespace) -> None:
    load_env()

    client = from_env()

    status_payload = {
        "type": "render_health_and_webhook_check",
        "at": utc_now_iso(),
        "ok": False,
        "admin_health": None,
        "latest_webhook": None,
        "incident": None,
    }

    try:
        status_payload["admin_health"] = client.get_json("/admin/health")
        status_payload["latest_webhook"] = client.get_json("/admin/billing/webhook/latest")
        status_payload["ok"] = True

        ev = status_payload.get("latest_webhook", {}).get("event")
        if ev and ev.get("verified") is False:
            status_payload["incident"] = {
                "type": "paypal_webhook_verification_failed",
                "event_type": ev.get("event_type"),
                "verification_status": ev.get("verification_status"),
                "verification_detail": ev.get("verification_detail"),
                "received_at": ev.get("received_at"),
            }

    except Exception as e:
        status_payload["detail"] = {"error": str(e)}

    # Persist deployment check
    deployments_dir = memory_root() / "deployments"
    out = deployments_dir / f"render_health_{datetime.utcnow().date().isoformat()}.json"
    write_json(out, status_payload)

    incident = status_payload.get("incident")

    if not status_payload["ok"]:
        inc = {
            "type": "incident",
            "at": utc_now_iso(),
            "service": "render",
            "summary": "Render/ReplyIQ admin health check failed",
            "context": status_payload.get("detail"),
        }
    elif incident:
        inc = {
            "type": "incident",
            "at": utc_now_iso(),
            "service": "paypal_webhook",
            "summary": "PayPal webhook verification failed",
            "context": incident,
        }
    else:
        inc = None

    if inc:
        inc_out = memory_root() / "incidents" / f"incident_{datetime.utcnow().isoformat()}.json"
        write_json(inc_out, inc)
        if not getattr(args, "dry_run", False):
            print(f"[infra-agent] incident written: {inc_out}")
    else:
        if not getattr(args, "dry_run", False):
            print(f"[infra-agent] ok, wrote {out}")
