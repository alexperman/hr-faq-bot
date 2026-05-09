import argparse
from datetime import datetime

from hermes.tools.env import load_env
from hermes.tools.paths import memory_root
from hermes.tools.storage import write_json, utc_now_iso


def run_kb_assist(args: argparse.Namespace) -> None:
    load_env()

    # MVP stub: suggest KB improvements (not uploading anything yet).
    payload = {
        "type": "kb_assist",
        "at": utc_now_iso(),
        "status": "stub",
        "suggestions": [
            "Add a standard 'Employee Handbook FAQ Index' doc to reduce search misses",
            "Ensure all policy sections include: effective date, exceptions, and escalation path",
            "Add 1-page 'Questions that must go to HR' policy to reduce wrong answers",
        ],
    }

    out = memory_root() / "product_recommendations" / f"kb_assist_{datetime.utcnow().date().isoformat()}.json"
    write_json(out, payload)
    if not getattr(args, "dry_run", False):
        print(f"[kb-agent] wrote {out}")
