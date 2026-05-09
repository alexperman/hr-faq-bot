import argparse
from datetime import datetime, timezone, timedelta
from pathlib import Path

from hermes.tools.paths import memory_root
from hermes.tools.storage import write_json, utc_now_iso


REQUIRED_MEMORY_DIRS = [
    "incidents",
    "deployments",
    "growth",
    "product",
    "customers",
    "summaries",
]


def _ensure_dirs() -> None:
    root = memory_root()
    for d in REQUIRED_MEMORY_DIRS:
        (root / d).mkdir(parents=True, exist_ok=True)


def _prune_old_files(days: int = 60) -> None:
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    for p in memory_root().rglob("*.json"):
        try:
            if datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc) < cutoff:
                p.unlink(missing_ok=True)
        except Exception:
            # Never fail the run because of cleanup.
            pass


def run_memory_maintenance(args: argparse.Namespace) -> None:
    _ensure_dirs()
    _prune_old_files(days=60)

    payload = {
        "type": "memory_maintenance",
        "at": utc_now_iso(),
        "pruned_json_older_than_days": 60,
    }

    out = memory_root() / "summaries" / f"memory_maintenance_{datetime.now().date().isoformat()}.json"
    write_json(out, payload)
    if not getattr(args, "dry_run", False):
        print(f"[memory-agent] wrote {out}")
