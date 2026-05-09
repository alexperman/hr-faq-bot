import argparse
from datetime import datetime

from hermes.tools.env import load_env
from hermes.tools.paths import memory_root
from hermes.tools.storage import write_json, utc_now_iso


def run_support(args: argparse.Namespace) -> None:
    load_env()

    # MVP stub: summarize last incidents.
    # Real implementation would call ReplyIQ admin APIs for incident/task queues.
    payload = {
        "type": "support_summary",
        "at": utc_now_iso(),
        "status": "stub",
        "note": "Wire to ReplyIQ admin endpoints when available.",
    }

    out = memory_root() / "summaries" / f"support_{datetime.utcnow().date().isoformat()}.json"
    write_json(out, payload)
    if not getattr(args, "dry_run", False):
        print(f"[support-agent] wrote {out}")
