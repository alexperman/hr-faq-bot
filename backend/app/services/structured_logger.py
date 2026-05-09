import json
import sys
from datetime import datetime, timezone
from typing import Any


def _ts_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def log_event(*, event: str, severity: str = "info", **extra: Any) -> None:
    """Emit a single-line JSON log record to stdout.

    Never include secrets or raw tokens in `extra`.
    """
    record = {
        "event": event,
        "severity": severity,
        "timestamp": _ts_iso(),
    }
    # filter out None values to keep logs concise
    for k, v in extra.items():
        if v is None:
            continue
        record[k] = v

    sys.stdout.write(json.dumps(record, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def log_audit(*, action: str, actor: str = "hermes", severity: str = "medium", **extra: Any) -> None:
    log_event(event="audit", severity=severity, action=action, actor=actor, **extra)
