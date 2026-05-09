from __future__ import annotations

from typing import TypedDict

# In-memory KB ingestion failure tracking (safe: no document content)
_kb_failure_events: list[dict] = []
_KB_FAILURE_HISTORY = 200


def record_kb_failure(*, tenant_slug: str | None, reason: str) -> None:
    _kb_failure_events.append({"tenant_slug": tenant_slug, "reason": reason})
    if len(_kb_failure_events) > _KB_FAILURE_HISTORY:
        del _kb_failure_events[: -_KB_FAILURE_HISTORY]


def get_kb_failure_stats() -> dict:
    counts: dict[str, int] = {}
    for ev in _kb_failure_events[-_KB_FAILURE_HISTORY:]:
        r = (ev.get("reason") or "unknown").strip()
        counts[r] = counts.get(r, 0) + 1

    return {
        "failures_total_recent": len(_kb_failure_events),
        "failures_by_reason_recent": counts,
        "recent_failures": _kb_failure_events[-10:],
    }
