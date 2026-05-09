import argparse
from datetime import datetime

from hermes.tools.env import load_env
from hermes.tools.paths import memory_root
from hermes.tools.storage import write_json, utc_now_iso


def run_analytics(args: argparse.Namespace) -> None:
    load_env()

    # MVP stub: until ReplyIQ has an analytics admin API.
    payload = {
        "type": "analytics_snapshot",
        "at": utc_now_iso(),
        "status": "stub",
        "next": [
            "Add ReplyIQ admin endpoints for conversion metrics (landing->trial, trial->active) by tenant/language",
            "Add Render deployment timeline capture",
        ],
    }

    out = memory_root() / "daily_summaries" / f"analytics_{datetime.utcnow().date().isoformat()}.json"
    write_json(out, payload)
    if not getattr(args, "dry_run", False):
        print(f"[analytics-agent] wrote {out}")
